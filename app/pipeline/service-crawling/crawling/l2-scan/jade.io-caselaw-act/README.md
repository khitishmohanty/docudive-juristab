Testing Your Web Scraper with Poetry, Pytest, and Coverage

This guide will walk you through setting up a professional testing environment for your project using modern Python tooling.Step 1: Prepare Your ProjectInstead of running multiple commands, we will create the configuration file directly. This is a much faster and more reliable method.Stop any running Poetry commands: Go to your terminal and press Ctrl+C.Create pyproject.toml: Replace the entire contents of the pyproject.toml file in your project root with the definitive version provided in the Canvas.Delete poetry.lock and requirements.txt: If you have a poetry.lock file, delete it. This will ensure you start fresh. You can also delete requirements.txt as it is no longer needed.Step 2: Install All DependenciesNow that you have the complete configuration file, you can install everything with a single command.poetry install
This command will read the pyproject.toml file, resolve the exact versions (which will be very fast now), create a poetry.lock file, and install everything into a virtual environment.Step 3: Project Structure for TestingYour project structure is good. We just need to add a tests directory to hold our test files. The structure should look like this:jade.io-caselaw-act/
├── config/
│   └── sitemap_jade_io.json
├── utils/
│   ├── __init__.py
│   ├── aws_utils.py
│   └── common.py
├── tests/
│   ├── __init__.py
│   ├── utils/
│   │   ├── __init__.py
│   │   └── test_aws_utils.py
│   ├── test_common.py
│   └── test_handler.py
├── .gitignore
├── Dockerfile
├── handler.py
└── pyproject.toml
Important: You need to add empty __init__.py files as shown above. This tells Python to treat these directories as packages, which is necessary for imports to work correctly during testing.Step 4: Run Tests and Generate ReportsWith everything installed, you can now run your tests and generate all the reports with a single command.poetry run pytest
This will now work correctly and create your reports in the reports/ directory as configured.