from setuptools import setup

setup(
    name='lambda_deploy',
    version='0.1',
    py_modules=['lambda_deploy'],
    install_requires=[
        'boto3',
        'Click',
        'PyYAML'
    ],
    entry_points='''
        [console_scripts]
        lambda-deploy=lambda_deploy:deploy
    ''',
)
