.PHONY: all app check clean motion test

all: app motion

app:
	npm run build

motion:
	$(MAKE) -C motiond all

check:
	npm run format:check
	npm run check
	npm run lint
	node --check web/app.js

test:
	npm test
	$(MAKE) -C motiond test

clean:
	rm -rf dist .test-dist motiond/build
