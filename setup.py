"""Compatibility shim for older pip editable installs.

All package metadata lives in ``pyproject.toml``. Modern installers use PEP
517; this file keeps Python 3.9 hosts with pre-PEP-660 pip deployable.
"""

from setuptools import find_packages, setup


setup(
    name="qingshan-short-drama-engine",
    version="0.3.1",
    description="MIT-licensed end-to-end AI film and short-drama production engine",
    packages=find_packages(include=("qingshan_engine", "qingshan_engine.*")),
    python_requires=">=3.9",
    entry_points={"console_scripts": ["qingshan=qingshan_engine.cli:main"]},
)
