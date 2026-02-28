.PHONY: update-examples update-examples-uv update-examples-npm

EXAMPLE_UV_DIRS := \
	examples/fastapi \
	examples/get-time \
	examples/shadcn \
	examples/ssr

EXAMPLE_NPM_DIRS := \
	examples/fastapi/src/mount/views \
	examples/get-time/src/get_time/views \
	examples/shadcn/src/shadcn/views \
	examples/ssr/src/ssr/views

update-examples: update-examples-uv update-examples-npm

update-examples-uv:
	@set -e; \
	for dir in $(EXAMPLE_UV_DIRS); do \
		echo "Updating uv dependencies in $$dir"; \
		(cd "$$dir" && uv lock --upgrade); \
	done

update-examples-npm:
	@set -e; \
	for dir in $(EXAMPLE_NPM_DIRS); do \
		echo "Updating npm dependencies in $$dir"; \
		(cd "$$dir" && npm update); \
	done
