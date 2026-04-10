CONDA_ENV  := neuro-rave
CONDA_RUN  := conda run -n $(CONDA_ENV)

.PHONY: setup setup-py setup-js build-c run run-sim dashboard compose-up-open clean-c clean all

# ── Python environment (conda) ────────────────────────────────────────────────
# Creates the conda env once; re-installs packages only when requirements.txt changes.

.conda-installed: requirements.txt
	conda env list | grep -q "^$(CONDA_ENV) " \
	    || conda create -n $(CONDA_ENV) python=3.11 -y
	$(CONDA_RUN) pip install -r requirements.txt
	touch .conda-installed

setup-py: .conda-installed
	@echo "Conda env '$(CONDA_ENV)' is ready."
	@echo ""
	@echo "System deps required for the C build:"
	@echo "  macOS:  brew install labstreaminglayer/tap/lsl libwebsockets"
	@echo "  Linux:  see https://github.com/sccn/liblsl  +  apt install libwebsockets-dev"

# ── JavaScript environment ────────────────────────────────────────────────────

setup-js:
	cd dashboard && npm install

# ── Combined setup ────────────────────────────────────────────────────────────

setup: setup-py setup-js

# ── C/C++ build ───────────────────────────────────────────────────────────────

build-c:
	cmake -B native/build native/
	cmake --build native/build --parallel

clean-c:
	rm -rf native/build

# ── Run targets ───────────────────────────────────────────────────────────────

run: .conda-installed
	$(CONDA_RUN) python main.py

run-sim: .conda-installed
	@echo "Tip: set \"SIMULATE\": true in config/constants.json to enable simulation mode."
	$(CONDA_RUN) python main.py

# ── Dashboard ─────────────────────────────────────────────────────────────────

dashboard: setup-js
	cd dashboard && npm run dev

compose-up-open:
	docker compose up -d
	@echo "Opening dashboard at http://127.0.0.1:5173"
	@open "http://127.0.0.1:5173"
	docker compose logs -f

# ── Composite / clean ─────────────────────────────────────────────────────────

all: setup build-c

clean: clean-c
	rm -f .conda-installed
