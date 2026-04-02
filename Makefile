# --- Configuration ---
PROJECT_NAME := poker-trainer
APP_NAME := poker-trainer 
PYTHON := venv/bin/python3

# --- Commands ---
.PHONY: all deploy build clean logs url test local-run db-start db-stop update wait-for-rollout check-tools check-login

# Default: Deploy everything
all: deploy

check-tools:
	@echo "🔍 Checking required tools..."
	@which oc > /dev/null || (echo "❌ 'oc' not found. Install OpenShift CLI." && exit 1)
	@which podman > /dev/null || (echo "❌ 'podman' not found. Install Podman." && exit 1)
	@which python3 > /dev/null || (echo "❌ 'python3' not found. Install Python 3." && exit 1)
	@which make > /dev/null || (echo "❌ 'make' not found. Install GNU Make." && exit 1)
	@echo "✅ All required tools are installed!"

# 1. Login check (ensure user is connected)
check-login:
	@oc whoami >/dev/null 2>&1 || (echo "❌ Error: Not logged in. Run 'oc login' first." && exit 1)
	@echo "✅ Logged in as $$(oc whoami)"

# 2. Create Project & Deploy
deploy: check-tools check-login
	@echo "🚀 Starting deployment to project: $(PROJECT_NAME)..."
	-oc new-project $(PROJECT_NAME) 2>/dev/null || echo "   (Project '$(PROJECT_NAME)' already exists, switching to it...)"
	@oc project $(PROJECT_NAME)
	@echo "📦 Applying configuration..."
	@oc apply -f openshift.yaml
	@echo "🏗️  Starting build..."
	@oc start-build $(APP_NAME) --from-dir=. --follow
	@echo "✅ Build complete! Waiting for rollout..."
	@$(MAKE) wait-for-rollout
	@$(MAKE) url

# 3. Trigger a rebuild (use this after code changes)
update: check-tools check-login
	@echo "🚀 Updating deployment in project: $(PROJECT_NAME)..."
	@echo "🔄 Updating application code..."
	@oc start-build $(APP_NAME) --from-dir=. --follow
	@$(MAKE) wait-for-rollout

# 4. Helper to wait for the app to be ready
wait-for-rollout:
	@echo "⏳ Waiting for deployment rollout..."
	@oc rollout status deployment/$(APP_NAME) --watch

# 5. Get the URL
url: check-tools check-login
	@echo "🌐 Retrieving application URL..."
	@echo "🎉 App is live at: http://$$(oc get route $(APP_NAME) -o jsonpath='{.spec.host}')"

# 6. Clean up (Delete everything)
clean:
	@echo "⚠️  Deleting project $(PROJECT_NAME)..."
	@oc delete project $(PROJECT_NAME)
	@echo "🗑️  Cleaned up."

# 7. Show logs
logs:
	@oc logs -f deployment/$(APP_NAME)

# 8. Local Development
test:
	@echo "🧪 Running tests..."
	@$(PYTHON) tests/test_integration.py

db-start:
	@echo "🐘 Starting local MongoDB (Podman)..."
	@podman run -d -p 27017:27017 --name poker-mongo docker.io/library/mongo:5.0 || podman start poker-mongo

db-stop:
	@echo "🛑 Stopping local MongoDB (Podman)..."
	@podman stop poker-mongo

local-run: db-start
	@echo "💻 Running locally on port 8080 (Debug Mode)..."
	@echo "   (Press Ctrl+C to stop the app, then run 'make db-stop' to stop the DB)"
	@export MONGO_URI="mongodb://localhost:27017/poker" && \
	export SECRET_KEY="dev-secret-key" && \
	export FLASK_DEBUG=1 && \
	$(PYTHON) app.py