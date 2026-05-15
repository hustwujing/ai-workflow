from setuptools import setup, find_packages

setup(
    name="cc-gitlab",
    version="1.0.0",
    packages=find_packages(),
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "ccg = cc.main:main",
        ],
    },
)
