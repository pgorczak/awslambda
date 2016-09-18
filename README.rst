awslambda
=========

*A tool for deploying Python projects to AWS Lambda.*


Usage
-----

::

  Usage: awslambda [OPTIONS] SOURCE_DIR S3_BUCKET

    Deploy Python code to AWS lambda.

    Zips the contents of the source directory together with optional pip
    requirements. The archive is temporarily uploaded to an S3 bucket and used
    to create or update lambda functions.

    Reference handlers from your source directory like you would in any Python
    module-tree (e.g. mymodule.myhandler, mymodule.mysubmodule.myhandler,
    etc.).

    Roles are ARNs like "arn:aws:iam::xxxxxxxxxxxx:role/myrole"

    YAML file entries for the sync option map function names to handlers and
    roles:

        myLambda:
            handler: mymodule.myhandler
            role: arn:aws:iam::xxxxxxxxxxxx:role/myrole

  Options:
    -r, --requirements PATH         pip compatible requirements file. Will be
                                    included in the archive.
    -c, --create NAME HANDLER ROLE  Create a new lambda function. Example:
                                    --create myLambda mymodule.myhandler myrole
    -u, --update NAME               Update a lambda function.
    -d, --delete NAME               Delete a lambda function.
    -s, --sync FILENAME             Keep lambdas defined in YAML file in sync
                                    with deployed lambdas.
    --help                          Show this message and exit.


Getting started
---------------
Authentication is left to *boto3* so you can set it up just like the `regular
AWS CLI <http://docs.aws.amazon.com/lambda/latest/dg/setup.html>`_. You need an
`S3 bucket
<http://docs.aws.amazon.com/AmazonS3/latest/gsg/CreatingABucket.html>`_ for
temporary storage. For a quick tutorial on execution roles, see the `official
docs
<http://docs.aws.amazon.com/lambda/latest/dg/with-s3-example-create-iam-role.html>`_
.
