import argparse
from contextlib import contextmanager
import os
import shutil
import sys
import tempfile
import zipfile

import pip
import boto3
import click

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
    """
    print '#', name
    try:
        with color('34'):
            yield
    except Exception as e:
        with color('31'):
            print e
        raise
    else:
        with color('32'):
            print 'OK'


class Progress(object):
    """ Progress callbacks for S3 upload.

    Example:
        s3.upload_file(
            'myfile.txt', 'mybucket', 'mykey',
            Callback=Progress(os.path.getsize('myfile.txt')),
    """
    def __init__(self, max_):
        self.n = 1.0/max_

    def __call__(self, dx):
        try:
            self.x += dx
        except AttributeError:
            print ''
            self.x = dx
        update_line('Uploading {:.0%}'.format(self.x * self.n))


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

    with do_thing('Putting code into S3: {}/{} [{:.2}MB]'.format(
            bucket, key, 1e-6 * size)):
        client.upload_file(
            filename, bucket, key,
            Callback=Progress(size),
            ExtraArgs={'ACL': 'private'})

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


def update_line(line):
    """ Overwrite the last line of stdout. """
    sys.stdout.write('\033[F{}\033[K\n'.format(line))


def zip_tree(zf, root, prefix=''):
    """ Add a file tree to a zip file.

    Args:
        zf: ZipFile object.
        root: root of the zipped file tree.
        prefix: prefix of the tree within the zip file.
    """
    print 'Packaging', root
    for path, dirs, files in os.walk(root, topdown=True):
        rel = os.path.relpath(path, root)
        for f in files:
            _, ext = os.path.splitext(f)
            if ext not in IGNORE_EXTENSIONS:
                update_line('Packaging '+f)
                filename = os.path.join(path, f)
                arcname = os.path.join(prefix, rel, f)
                zf.write(filename, arcname)
    update_line('done')


@click.command(
    help='Deploy to AWS lambda. Zips the contents of a source directory'
         ' together with requirements from a pip-compatible file. That file is'
         ' temporarily uploaded to an S3 bucket and used to create or update'
         ' lambda functions.')
@click.argument('source_dir', type=click.Path(
    exists=True, file_okay=False, dir_okay=True, readable=True,
    resolve_path=True))
@click.argument('requirements', type=click.Path(
    exists=True, file_okay=True, dir_okay=False, readable=True,
    resolve_path=True))
@click.argument('s3_bucket')
@click.option(
    '--create', '-c', multiple=True, nargs=3, metavar='name handler role_arn',
    default=[],
    help=('Create a new lambda function. Example: --create myLambda '
          'mymodule.myhandler arn:aws:iam::xxxxxxxxxxxx:role/myrole'))
@click.option(
        '--update', '-u', multiple=True, metavar='name', default=[],
        help='Update a lambda function.')
def deploy_lambda(source_dir, requirements, s3_bucket, create, update):
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
            s3 = boto3.client('s3')

        with temp_s3file(s3, zf_path, s3_bucket) as (bucket, key):
            for name, handler, role_arn in create:
                with do_thing('Creating {} ({}) with {}'.format(
                        name, handler, role_arn)):
                    lambda_.create_function(
                        FunctionName=name,
                        Runtime='python2.7',
                        Role=role_arn,
                        Handler=handler,
                        Code={'S3Bucket': bucket, 'S3Key': key}
                    )

            for name in update:
                with do_thing('Updating {}'.format(name)):
                    lambda_.update_function_code(
                        FunctionName=name,
                        S3Bucket=bucket,
                        S3Key=key
                    )

deploy_lambda()
