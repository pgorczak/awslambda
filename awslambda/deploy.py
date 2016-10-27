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


class ColoredStream(object):
    """ Color code stream.

    See https://en.wikipedia.org/wiki/ANSI_escape_code#Colors.
    Use 31 for red, 31;1 for bright red, etc.
    """
    def __init__(self, stream, color):
        self.__c = '\033[{}m'.format(color)
        self.__s = stream
        self.__l = 0

    def __len__(self):
        return self.__l

    def write(self, msg):
        self.__s.write('{}{}\033[0m'.format(self.__c, msg))
        self.__l += len(msg)

    def flush(self):
        self.__s.flush()
        
    def isatty(self):
        return self.__s.isatty()
    

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
    label = '[{}]'.format(name)
    print label
    sys.stdout.flush()
    sys.stderr.flush()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    c_out, c_err = ColoredStream(sys.stdout, 34), ColoredStream(sys.stderr, 31)
    sys.stdout, sys.stderr = c_out, c_err
    try:
        yield
    except:
        raise
    else:
        if len(c_out) + len(c_err) == 0:
            old_stdout.write('\033[F')
        old_stdout.write('{} \033[32mOK\033[0m\n'.format(label))
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        sys.stdout, sys.stderr = old_stdout, old_stderr


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


def pip_install(path, requirements):
    result = pip.main(['install', '-r', requirements, '-t', path, '--isolated',
                       '--no-compile'])
    if result != 0:
        raise RuntimeError


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
@click.argument('s3_bucket')
@click.option(
    '--requirements', '-r', type=click.Path(
        exists=True, file_okay=True, dir_okay=False, readable=True,
        resolve_path=True),
    help='pip compatible requirements file. Will be included in the archive.')
@click.option(
    '--create', '-c', multiple=True, nargs=3, metavar='NAME HANDLER ROLE',
    default=[],
    help='Create a new lambda function. Example:\n\n--create myLambda '
         'mymodule.myhandler myrole')
@click.option(
    '--update', '-u', multiple=True, metavar='NAME', default=[],
    help='Update a lambda function.')
@click.option(
    '--delete', '-d', multiple=True, metavar='NAME', default=[],
    help='Delete a lambda function.')
@click.option(
    '--sync', '-s', multiple=True, type=click.File(),
    help='Keep lambdas defined in YAML file in sync with deployed lambdas.')
def deploy(source_dir, requirements, s3_bucket, create, update, delete, sync):
    """ Deploy Python code to AWS lambda.

    Zips the contents of the source directory together with optional pip
    requirements. The archive is temporarily uploaded to an S3 bucket and used
    to create or update lambda functions.

    Reference handlers from your source directory like you would in any Python
    module-tree (e.g. mymodule.myhandler, mymodule.mysubmodule.myhandler,
    etc.).

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
            if requirements is not None:
                with do_thing('Collecting requirements'):
                    pip_install(tmp, requirements)
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
            delete, create, update = map(list, (delete, create, update))

            for f in sync:
                cfg = yaml.safe_load(f)
                for name, value in cfg.iteritems():
                    handler = value['handler']
                    role = value['role']
                    if name in lambdas:
                        if lambdas.is_equivalent(name, handler, role):
                            update.append(name)
                        else:
                            delete.append(name)
                            create.append((name, handler, role))
                    else:
                        create.append((name, handler, role))

            with do_thing('Deleting functions'):
                for name in delete:
                    print lambdas.describe(name)
                    lambda_.delete_function(FunctionName=name)

            with do_thing('Creating functions'):
                for name, handler, role in create:
                    print Lambdas.description(name, handler, role)
                    lambda_.create_function(
                        FunctionName=name,
                        Runtime='python2.7',
                        Role=role,
                        Handler=handler,
                        Code={'S3Bucket': bucket, 'S3Key': key})

            with do_thing('Updating functions'):
                for name in update:
                    print lambdas.describe(name)
                    lambda_.update_function_code(
                        FunctionName=name,
                        S3Bucket=bucket,
                        S3Key=key)
