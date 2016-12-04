awslambda
=========

*A tool for deploying Python projects to AWS Lambda.*

Getting started
---------------
Authentication is left to *boto3* so you can set it up just like the `regular
AWS CLI <http://docs.aws.amazon.com/lambda/latest/dg/setup.html>`_. You need an
`S3 bucket
<http://docs.aws.amazon.com/AmazonS3/latest/gsg/CreatingABucket.html>`_ for
temporary storage. For a quick tutorial on execution roles, see the `official
docs
<http://docs.aws.amazon.com/lambda/latest/dg/with-s3-example-create-iam-role.html>`_
(of course you need one that can execute lambdas).

In a new folder, create *mymodule.py*:

.. code:: python

    def hello(*args):
        return "Hello, world!"


Then deploy the function (fill in your execution role resource name from the AWS
console):

::

    awslambda . mybucket --create hello mymodule.hello arn:aws:iam::xxxxxxxxxxxx:role/myrole


From now on, if you make changes to the function, just run:

::

    awslambda . mybucket --update hello


You can use as many options as you like (shown here with shorthand names):

::

    awslambda . mybucket -u hello -u myotherlambda --delete myoldlambda


Or specify your functions in a YAML file (lets call it *sync.yaml*):

.. code:: yaml

    hello:
        handler: mymodule.hello
        role: arn:aws:iam::xxxxxxxxxxxx:role/myrole
    # myotherlambda:
    #     handler: myothermodule.myotherhandler
    #     role: arn:aws:iam::xxxxxxxxxxxx:role/myrole

Syncing from a file, *awslambda* will update existing functions and create the
others automatically.

::

    awslambda . mybucket --sync sync.yaml


To add dependencies, use your `pip *requirements.txt*
<https://pip.readthedocs.io/en/stable/user_guide/#requirements-files>`_:

::

    awslambda . mybucket -s sync.yaml --requirements requirements.txt


A template greeting page
........................

Let's use the features introduced above to create a greeting page. We will use
the `Jinja2<http://jinja.pocoo.org>`_ templating engine.
Edit *mymodule.py*

.. code:: python

    from jinja2 import Template

    template = Template('''
    <html>
      <body>
        <h1>Hello, {{ parameters.name }}!</h1>
        <p>{{ parameters.message }}</p>
      </body>
    </html>
    ''')


    def hello(event, context):
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'text/HTML'},
            'body': template.render(parameters=event['queryStringParameters'])}


And create your simple *requirements.txt*

::

    Jinja2


Deploy

::

      awslambda . mybucket -s sync.yaml -r requirements.txt


Open the function in your AWS console. Go to *Triggers* and add an
*API Gateway* trigger. Set security to *Open* for now. Open the URL of the
created trigger in your browser. You should see "Hello, !". To customize the
page append e.g.

::

    ?name=Commander Shepard&message=You've received a new message at your private terminal.


to the URL.


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
