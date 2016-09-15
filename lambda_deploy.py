import collections
from contextlib import contextmanager
import os
import shutil
import sys
import tempfile
import zipfile

import boto3
import click
import pip
import yaml

IGNORE_EXTENSIONS = ('.pyc',)


@contextmanager
def color(code):
    """ Color code stdout.

    See https://en.wikipedia.org/wiki/ANSI_escape_code#Colors.
    Use 31 for red, 31;1 for bright red, etc.

    Example:
        with color('31'):
            print 'error'
    """
    sys.stdout.write('\033[{}m'.format(code))
    try:
        yield
    finally:
        sys.stdout.write('\033[0m')


@contextmanager
def do_thing(name):
    """ Logging helper.

    Surrounds any output in the context with name and a green OK. If an error
    occurs, it is printed in red. Output in context is colored blue.

    Example:
        with do_thing('Sleeping') as result:
            print 'Woke up.'
        # Sleeping...
        # Woke up.
        # Sleeping... OK
    """
    label = '# {}... '.format(name)
    print label
    try:
        with color('34'):
            yield
    except Exception as e:
        with color('31'):
            print e
        raise
    else:
        sys.stdout.write(label)
        with color('32'):
            print 'OK'


class Lambdas(object):
    """ Helper class for existing lambdas. """
    Props = collections.namedtuple('Props', 'handler role')

    def __init__(self, client):
        """ Initialize with lambda client. """
        self.functions = {
            f['FunctionName']: self.Props(handler=f['Handler'], role=f['Role'])
            for f in client.list_functions()['Functions']}

    def __contains__(self, name):
        """ Check if a function with name exists. """
        return name in self.functions

    def __getitem__(self, name):
        return self.functions[name]

    def is_equivalent(self, name, handler, role):
        """ Check if a function with name has a specific handler and role. """
        return self.Props(handler, role) == self[name]

    def describe(self, name):
        """ Get a string describing a function. """
        p = self[name]
        return self.description(name, p.handler, p.role)

    @staticmethod
    def description(name, handler, role):
        """ Get a string describing a function. """
        return '{} ({}) with {}'.format(name, handler, role)


@contextmanager
def temp_dir():
    """ Temporary directory. Yields path as string.

    Example:
        with temp_dir() as dir:
            print 'The temp dir is at', dir
    """
    path = tempfile.mkdtemp()
    try:
        yield path
    finally:
        shutil.rmtree(path)


@contextmanager
def temp_s3file(client, filename, bucket):
    """ Temporary file in S3.

    Example:
        s3 = boto3.client('s3')
        with temp_s3file(s3, 'mypath/myfile.txt', 'mybucket') as bucket, key:
            print key  # myfile.txt
            s3.copy({'Bucket': bucket, 'Key': key},
                    'myotherbucket', 'mycopiedfile.txt')
    """
    key = os.path.basename(filename)
    size = os.path.getsize(filename)

    with do_thing('Putting code into S3'.format(bucket)):
        print 'Uploading {}/{} [{:.2}MB]'.format(bucket, key, 1e-6 * size)

        def cb(x):
            sys.stdout.write('.')
            sys.stdout.flush()

        client.upload_file(
            filename, bucket, key,
            Callback=cb,
            ExtraArgs={'ACL': 'private'})
        print ''
    try:
        yield bucket, key
    finally:
        client.delete_object(Bucket=bucket, Key=key)


@contextmanager
def temp_zipfile():
    """ Temporary zip file.

    Example:
        with temp_zipfile() as zf:
            zf.write('myfile.txt')
    """
    fd, path = tempfile.mkstemp(suffix='.zip')
    zf = zipfile.ZipFile(os.fdopen(fd, 'wb'), 'w', zipfile.ZIP_DEFLATED)
    try:
        yield zf, path
    finally:
        del zf
        os.remove(path)


def zip_tree(zf, root, prefix=''):
    """ Add a file tree to a zip file.

    Args:
        zf: ZipFile object.
        root: root of the zipped file tree.
        prefix: prefix of the tree within the zip file.
    """
    for path, dirs, files in os.walk(root, topdown=True):
        rel = os.path.relpath(path, root)
        if os.path.basename(path).startswith('.'):
            dirs[:] = []
            continue
        for f in files:
            _, ext = os.path.splitext(f)
            if ext not in IGNORE_EXTENSIONS and not f.startswith('.'):
                filename = os.path.join(path, f)
                arcname = os.path.join(prefix, rel, f)
                print 'Packaging', arcname
                zf.write(filename, arcname)


@click.command()
@click.argument('source_dir', type=click.Path(
    exists=True, file_okay=False, dir_okay=True, readable=True,
    resolve_path=True))
@click.argument('requirements', type=click.Path(
    exists=True, file_okay=True, dir_okay=False, readable=True,
    resolve_path=True))
@click.argument('s3_bucket')
@click.option(
    '--create', '-c', multiple=True, nargs=3, metavar='name handler role',
    default=[],
    help='Create a new lambda function. Example: --create myLambda myrole')
@click.option(
    '--update', '-u', multiple=True, metavar='name', default=[],
    help='Update a lambda function.')
@click.option(
    '--sync', '-s', multiple=True, metavar='file', type=click.File(),
    help='Keep lambdas defined in YAML file in sync with deployed lambdas.')
def deploy_lambda(source_dir, requirements, s3_bucket, create, update, sync):
    """ Deploy to AWS lambda.

    Zips the contents of a source directory together with requirements from a
    pip-compatible file. That file is temporarily uploaded to an S3 bucket and
    used to create or update lambda functions.

    Roles are ARNs like "arn:aws:iam::xxxxxxxxxxxx:role/myrole"

    YAML file entries for the sync option map function names to handlers and
    roles:

    \b
        myLambda:
            handler: mymodule.myhandler
            role: arn:aws:iam::xxxxxxxxxxxx:role/myrole
    """
    with temp_zipfile() as (zf, zf_path):
        with temp_dir() as tmp:
            with do_thing('Collecting requirements'):
                result = pip.main([
                    'install', '-r', requirements, '-t', tmp, '--isolated',
                    '--no-compile'])
                if result != 0:
                    raise RuntimeError

            with do_thing('Packaging requirements'):
                zip_tree(zf, tmp)

        with do_thing('Packaging code'):
            zip_tree(zf, source_dir)

        zf.close()

        with do_thing('Connecting to AWS'):
            lambda_ = boto3.client('lambda')
            lambdas = Lambdas(lambda_)
            s3 = boto3.client('s3')

        with temp_s3file(s3, zf_path, s3_bucket) as (bucket, key):
            def do_create(name, handler, role):
                with do_thing('Creating function.'):
                    print Lambdas.description(name, handler, role)
                    lambda_.create_function(
                        FunctionName=name,
                        Runtime='python2.7',
                        Role=role,
                        Handler=handler,
                        Code={'S3Bucket': bucket, 'S3Key': key}
                    )

            def do_update(name):
                with do_thing('Updating function'):
                    print lambdas.describe(name)
                    lambda_.update_function_code(
                        FunctionName=name,
                        S3Bucket=bucket,
                        S3Key=key
                    )

            def do_recreate(name, handler, role):
                with do_thing('Deleting function'):
                    print lambdas.describe(name)
                    lambda_.delete_function(FunctionName=name)
                do_create(name, handler, role)

            def do_sync(f):
                cfg = yaml.safe_load(f)
                for name, value in cfg.iteritems():
                    handler = value['handler']
                    role = value['role']
                    if name in lambdas:
                        if lambdas.is_equivalent(name, handler, role):
                            do_update(name)
                        else:
                            do_recreate(name, handler, role)
                    else:
                        do_create(name, handler, role)

            map(do_create, create)
            map(do_update, update)
            map(do_sync, sync)


deploy_lambda()
