from codecs import open
from os import path
from setuptools import find_packages, setup

here = path.abspath(path.dirname(__file__))

with open(path.join(here, 'README.rst'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='awslambda',
    version='1.0.3',
    description='A tool for deploying Python projects to AWS Lambda.',
    long_description=long_description,
    keywords='aws lambda',
    url='https://github.com/pgorczak/awslambda',
    license='GPLv3',
    author='Philipp Gorczak',
    author_email='p.gorczak@gmail.com',
    packages=find_packages(),
    install_requires=[
        'boto3',
        'click',
        'PyYAML'
    ],
    entry_points='''
        [console_scripts]
        awslambda=awslambda:deploy
    ''',
    classifiers=[
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Programming Language :: Python :: 2.7',
        'Topic :: Internet :: WWW/HTTP :: Site Management',
        'Topic :: System :: Software Distribution',
        'Topic :: Utilities',
    ]
)
