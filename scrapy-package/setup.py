import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="scrapy-tw-rental-house",
    version="1.0.0",
    author="ddio",
    author_email="ddio@ddio.io",
    description="Scrapy spider for TW Rental House",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/g0v/tw-rental-house-data/tree/master/scrapy-package",
    include_package_data=True,
    packages=setuptools.find_packages(
        exclude=['trial', 'examples']
    ),
    install_requires=[
        'Scrapy>=1'
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
