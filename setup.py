from setuptools import setup, find_packages

try:
    with open("README.md", "r", encoding="utf-8") as f:
        long_description = f.read()
except UnicodeDecodeError:
    with open("README.md", "r", encoding="latin-1") as f:
        long_description = f.read()

setup(
    name="AD-SearchAPI",
    version="2.0.3",
    packages=find_packages(),
    install_requires=[
        "requests>=2.31.0",
        "phonenumbers>=8.13.0",
        "python-dateutil>=2.8.2",
        "typing-extensions>=4.7.0",
        "urllib3>=2.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
            "mypy>=1.0.0",
        ],
        "brotli": [
            "brotli>=1.0.0",
        ],
    },
    author="Search API Team",
    author_email="support@search-api.dev",
    description="A comprehensive Python client library for the Search API with enhanced error handling and balance management",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/AntiChrist-Coder/search_api_library",
    keywords=[
        "search-api",
        "email-search",
        "phone-search",
        "domain-search",
        "people-search",
        "api-client",
        "balance-management",
    ],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Internet :: WWW/HTTP :: Dynamic Content",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Communications :: Email",
        "Topic :: Internet :: Name Service (DNS)",
    ],
    python_requires=">=3.8",
    project_urls={
        "Bug Reports": "https://github.com/AntiChrist-Coder/search_api_library/issues",
        "Source": "https://github.com/AntiChrist-Coder/search_api_library",
        "Documentation": "https://github.com/AntiChrist-Coder/search_api_library/blob/main/README.md",
    },
) 
