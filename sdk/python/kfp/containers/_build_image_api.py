# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the speci

__all__ = [
    'build_image_from_working_dir',
]


import logging
import os
import re
import shutil
import sys
import tempfile

import requests

from ..compiler._container_builder import ContainerBuilder


default_base_image = 'gcr.io/deeplearning-platform-release/tf-cpu.1-14'


_container_work_dir = '/python_env'


_default_image_builder = None


def _get_default_image_builder():
    global _default_image_builder
    if _default_image_builder is None:
        from ..compiler._container_builder import ContainerBuilder
        _default_image_builder = ContainerBuilder()
    return _default_image_builder


def _generate_dockerfile_text(context_dir: str, dockerfile_path: str, base_image: str = None) -> str:
    # Generating the Dockerfile
    logging.info('Generating the Dockerfile')

    requirements_rel_path = 'requirements.txt'
    requirements_path = os.path.join(context_dir, requirements_rel_path)
    requirements_file_exists = os.path.exists(requirements_path)

    if not base_image:
        base_image = default_base_image
    if callable(base_image):
        base_image = base_image()

    dockerfile_lines = []
    dockerfile_lines.append('FROM {}'.format(base_image))
    dockerfile_lines.append('WORKDIR {}'.format(_container_work_dir))
    if requirements_file_exists:
        dockerfile_lines.append('COPY {} .'.format(requirements_rel_path))
        dockerfile_lines.append('RUN python3 -m pip install -r {}'.format(requirements_rel_path))
    dockerfile_lines.append('COPY . .')

    return '\n'.join(dockerfile_lines)


def build_image_from_working_dir(image_name: str = None, working_dir: str = None, file_filter_re: str = r'.*\.py',  timeout: int = 1000, base_image: str = None, builder: ContainerBuilder = None) -> str:
    '''build_image_from_working_dir builds and pushes a new container image that captures the current python working directory.

    This function recursively scans the working directory and captures the following files in the container image context:
    * requirements.txt files
    * all python files (can be overridden by passing a different `file_filter_re` argument)

    The function generates Dockerfile that starts from a python container image, install packages from requirements.txt (if present) and copies all the captured python files to the container image.
    The Dockerfile can be overridden by placing a custom Dockerfile in the root of the working directory.

    Args:
        image_name: Optional. The image repo name where the new container image will be pushed. The name will be generated if not not set.
        working_dir: Optional. The directory that will be captured. The current directory will be used if omitted.
        file_filter_re: Optional. A regular expression that will be used to decide which files to include in the container building context.
        timeout: Optional. The image building timeout in seconds.
        base_image: Optional. The container image to use as the base for the new image. If not set, the Google Deep Learning Tensorflow CPU image will be used.
        builder: Optional. An instance of ContainerBuilder or compatible class that will be used to build the image.

    Returns:
        The full name of the container image including the hash digest. E.g. gcr.io/my-org/my-image@sha256:86c1...793c.
    '''
    current_dir = working_dir or os.getcwd()
    with tempfile.TemporaryDirectory() as context_dir:
        logging.info('Creating the build context directory: {}'.format(context_dir))

        # Copying all *.py and requirements.txt files
        for dirpath, dirnames, filenames in os.walk(current_dir):
            dst_dirpath = os.path.join(context_dir, os.path.relpath(dirpath, current_dir))
            os.makedirs(dst_dirpath, exist_ok=True)
            for file_name in filenames:
                if re.match(file_filter_re, file_name) or file_name == 'requirements.txt':
                    src_path = os.path.join(dirpath, file_name)
                    dst_path = os.path.join(dst_dirpath, file_name)
                    shutil.copy(src_path, dst_path)

        src_dockerfile_path = os.path.join(current_dir, 'Dockerfile')
        dst_dockerfile_path = os.path.join(context_dir, 'Dockerfile')
        if os.path.exists(src_dockerfile_path):
            if base_image:
                raise ValueError('Cannot specify base_image when using custom Dockerfile (which already specifies the base image).')
            shutil.copy(src_dockerfile_path, dst_dockerfile_path)
        else:
            dockerfile_text = _generate_dockerfile_text(context_dir, dst_dockerfile_path, base_image)
            with open(dst_dockerfile_path, 'w') as f:
                f.write(dockerfile_text)

        if builder is None:
            builder = _get_default_image_builder()
        return builder.build(
            local_dir=context_dir,
            target_image=image_name,
            timeout=timeout,
        )
