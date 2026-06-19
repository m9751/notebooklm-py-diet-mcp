# notebooklm-py-diet-mcp — canonical command front door (mirrors .github/workflows/ci.yml exactly)
.PHONY: help install lint test

help:		## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-10s %s\n",$$1,$$2}'

install:	## install runtime + dev deps (matches CI)
	pip install "ruff==0.15.1"
	pip install "notebooklm-py[browser]>=0.3.2" "mcp[cli]>=1.0.0"
	pip install pytest pytest-asyncio pytest-cov

lint:		## ruff check + ruff format --check (exactly what CI runs)
	ruff check .
	ruff format --check .

test:		## pytest with coverage (matches CI)
	pytest tests/ -v --tb=short --cov=notebooklm_mcp_server --cov-report=term-missing
