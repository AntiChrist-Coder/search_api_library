from setuptools import setup, find_packages

setup(
    name="search-api-library",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "requests>=2.31.0",
        "phonenumbers>=8.13.0",
        "python-dateutil>=2.8.2",
        "cachetools>=5.3.0",
        "typing-extensions>=4.7.0",
    ],
    author="Search API Team",
    author_email="support@search-api.dev",
    description="A Python client library for the Search API",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/search-api-python",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.7",
) 