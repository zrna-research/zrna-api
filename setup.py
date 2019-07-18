#!/usr/bin/env python
# -*- coding: utf-8 -*-

import io
import os
import sys
from shutil import rmtree

from setuptools import find_packages, setup, Command

# python3 setup.py upload

NAME = 'zrna'
DESCRIPTION = 'API client for the Zrna software-defined analog platform.'
URL = 'https://github.com/zrna-research/zrna-api'
EMAIL = 'nicolas@zrna.org'
AUTHOR = 'Nicolas Steven Miller'
REQUIRES_PYTHON = '>=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*, !=3.5.*, <4'

VERSION = '1.0.6'

REQUIRED = [
    'cobs',
    'future',
    'inflection',
    'protobuf',
    'pyserial'
]

here = os.path.abspath(os.path.dirname(__file__))

try:
    with io.open(os.path.join(here, 'README_PYPI.md'), encoding='utf-8') as f:
        long_description = '\n' + f.read()
except FileNotFoundError:
    long_description = DESCRIPTION

about = {}
if not VERSION:
    project_slug = NAME.lower().replace("-", "_").replace(" ", "_")
    with open(os.path.join(here, project_slug, '__version__.py')) as f:
        exec(f.read(), about)
else:
    about['__version__'] = VERSION


class UploadCommand(Command):
    """Support setup.py upload."""

    description = 'Build and publish the package.'
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        try:
            print('Removing previous builds')
            rmtree(os.path.join(here, 'dist'))
        except OSError:
            pass

        print('Building Source and Wheel (universal) distribution')
        os.system('{0} setup.py sdist bdist_wheel --universal'.format(sys.executable))

        print('Uploading the package to PyPI via Twine')
        os.system('twine upload dist/*')

        print('Pushing git tags')
        os.system('git tag v{0}'.format(about['__version__']))
        os.system('git push --tags')

        sys.exit()

setup(
    name=NAME,
    version=about['__version__'],
    description=DESCRIPTION,
    long_description=long_description,
    long_description_content_type='text/markdown',
    author=AUTHOR,
    author_email=EMAIL,
    python_requires=REQUIRES_PYTHON,
    url=URL,
    packages=find_packages(exclude=["tests", "*.tests", "*.tests.*", "tests.*"]),
    install_requires=REQUIRED,
    include_package_data=True,
    license='APACHE',
    classifiers=[
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6'
    ],
    cmdclass={
        'upload': UploadCommand,
    },
)
