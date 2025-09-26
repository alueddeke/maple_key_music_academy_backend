# Testing Workflow for Maple Key Music Academy

## 🎯 **Docker-First Testing Approach**

This follows your existing team workflow and keeps everything consistent with your Docker setup.

## 🚀 **Running Tests (Docker Way)**

### **Option 1: Test Inside Running Container**
```bash
# Start your development environment
cd maple_key_music_academy_docker
docker-compose up -d

# Run tests inside the API container
docker-compose exec api pytest billing/tests.py --cov=billing --cov-report=term --cov-report=html
```

### **Option 2: Test as Part of Development**
```bash
# Run tests every time you make changes
docker-compose exec api pytest billing/tests.py -v# Maple Key Music Academy - Development Workflow

## 🎯 **Automatic Dependency Management**

Your Docker setup now handles dependencies automatically! No more local `npm install` needed.

## 🚀 **When Pulling Changes with New Dependencies**

### **When a team member adds new dependencies:**
```bash
# 1. Fetch changes from remote
git fetch origin
git checkout feature-branch

# 2. Rebuild containers (installs new dependencies automatically)
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# 3. That's it! Your database and superuser are still there
```

### **When only source code changes (no new dependencies):**
```bash
# 1. Fetch changes
git pull origin feature-branch

# 2. Just restart containers (faster)
docker-compose restart

# 3. Or if you want to be safe:
docker-compose down
docker-compose build
docker-compose up -d
```

## 🔧 **Adding Dependencies (For Any Developer)**

### **Adding new dependencies:**
```bash
# Add new dependency
npm install some-new-library

# Commit and push
git add package.json package-lock.json
git commit -m "Add some-new-library"
git push origin feature-branch
```

**Other team members will need to rebuild when they pull your changes.**

## 📋 **What's Different Now**

### **✅ What You Keep:**
- All database data
- Your superuser account
- All existing records
- Database schema and migrations

### **🔄 What Gets Updated:**
- Frontend dependencies (installed automatically)
- Backend dependencies (installed automatically)
- Container cache (rebuilds fresh)

## 🛠️ **Development Commands**

### **Start Development Environment:**
```bash
cd maple_key_music_academy_docker
docker-compose up -d
```

### **Stop Development Environment:**
```bash
docker-compose down
```

### **View Logs:**
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f frontend
docker-compose logs -f api
```

### **Rebuild After Dependency Changes:**
```bash
docker-compose down
docker-compose build --no-cache
```

## 🎯 **Key Benefits**

1. **No local dependencies** - Everything runs in Docker
2. **Consistent environments** - All team members have identical setups
3. **Data persistence** - Database survives all rebuilds
4. **Easy dependency management** - Just rebuild when dependencies change
5. **Hot reloading** - Source code changes still work instantly

## 🚨 **Important Notes**

- **Always use `--no-cache`** when dependencies might have changed
- **Your database data is safe** - It's stored in Docker volumes
- **No local `npm install`** needed anymore
- **Source code changes** still hot-reload instantly
- **Dependency changes** require container rebuild

## 🔍 **Troubleshooting**

### **If something breaks:**
```bash
# Check container status
docker-compose ps

# View logs
docker-compose logs -f

# Rebuild everything
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### **If database issues:**
```bash
# Check database volume
docker volume ls | grep postgres

# Database is safe in the volume!
```
# Maple Key Music Academy - Development Workflow

## 🎯 **Automatic Dependency Management**

Your Docker setup now handles dependencies automatically! No more local `npm install` needed.

## 🚀 **When Pulling Changes with New Dependencies**

### **When a team member adds new dependencies:**
```bash
# 1. Fetch changes from remote
git fetch origin
git checkout feature-branch

# 2. Rebuild containers (installs new dependencies automatically)
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# 3. That's it! Your database and superuser are still there
```

### **When only source code changes (no new dependencies):**
```bash
# 1. Fetch changes
git pull origin feature-branch

# 2. Just restart containers (faster)
docker-compose restart

# 3. Or if you want to be safe:
docker-compose down
docker-compose build
docker-compose up -d
```

## 🔧 **Adding Dependencies (For Any Developer)**

### **Adding new dependencies:**
```bash
# Add new dependency
npm install some-new-library

# Commit and push
git add package.json package-lock.json
git commit -m "Add some-new-library"
git push origin feature-branch
```

**Other team members will need to rebuild when they pull your changes.**

## 📋 **What's Different Now**

### **✅ What You Keep:**
- All database data
- Your superuser account
- All existing records
- Database schema and migrations

### **🔄 What Gets Updated:**
- Frontend dependencies (installed automatically)
- Backend dependencies (installed automatically)
- Container cache (rebuilds fresh)

## 🛠️ **Development Commands**

### **Start Development Environment:**
```bash
cd maple_key_music_academy_docker
docker-compose up -d
```

### **Stop Development Environment:**
```bash
docker-compose down
```

### **View Logs:**
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f frontend
docker-compose logs -f api
```

### **Rebuild After Dependency Changes:**
```bash
docker-compose down
docker-compose build --no-cache
```

## 🎯 **Key Benefits**

1. **No local dependencies** - Everything runs in Docker
2. **Consistent environments** - All team members have identical setups
3. **Data persistence** - Database survives all rebuilds
4. **Easy dependency management** - Just rebuild when dependencies change
5. **Hot reloading** - Source code changes still work instantly

## 🚨 **Important Notes**

- **Always use `--no-cache`** when dependencies might have changed
- **Your database data is safe** - It's stored in Docker volumes
- **No local `npm install`** needed anymore
- **Source code changes** still hot-reload instantly
- **Dependency changes** require container rebuild

## 🔍 **Troubleshooting**

### **If something breaks:**
```bash
# Check container status
docker-compose ps

# View logs
docker-compose logs -f

# Rebuild everything
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### **If database issues:**
```bash
# Check database volume
docker volume ls | grep postgres

# Database is safe in the volume!
```

## 📞 **Need Help?**

- Check container logs: `docker-compose logs -f`
- Verify containers are running: `docker-compose ps`
- Rebuild if needed: `docker-compose build --no-cache`
- Your database data is always safe in Docker volumes!

---

**Happy coding! 🎵**

## 📞 **Need Help?**

- Check container logs: `docker-compose logs -f`
- Verify containers are running: `docker-compose ps`
- Rebuild if needed: `docker-compose build --no-cache`
- Your database data is always safe in Docker volumes!

---

**Happy coding! 🎵**


# Run with coverage
docker-compose exec api pytest billing/tests.py --cov=billing --cov-report=html
```

### **Option 3: Add Testing to Docker Compose**
Add a testing service to your docker-compose.yaml:

```yaml
# Add this to your docker-compose.yaml
  test:
    build:
      context: ../maple_key_music_academy_backend
      dockerfile: Dockerfile
    container_name: maple_key_test
    env_file:
      - ./.envs/env.dev
    depends_on:
      db:
        condition: service_healthy
    command: pytest billing/tests.py --cov=billing --cov-report=html
    volumes:
      - ../maple_key_music_academy_backend:/usr/app/
```

## 🔧 **Development Workflow with Testing**

### **Daily Development:**
```bash
# 1. Start development environment
cd maple_key_music_academy_docker
docker-compose up -d

# 2. Make code changes
# (your changes are automatically reflected)

# 3. Run tests
docker-compose exec api pytest billing/tests.py -v

# 4. Run with coverage
docker-compose exec api pytest billing/tests.py --cov=billing --cov-report=html
```

### **When Adding New Dependencies:**
```bash
# 1. Add to requirements.txt (like you did)
# 2. Commit and push
git add requirements.txt
git commit -m "Add testing dependencies"
git push origin feature-branch

# 3. Team members rebuild (as per your workflow guide)
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

## 📋 **Testing Commands**

### **Basic Testing:**
```bash
# Run all tests
docker-compose exec api pytest billing/tests.py

# Run with verbose output
docker-compose exec api pytest billing/tests.py -v

# Run specific test
docker-compose exec api pytest billing/tests.py::BillingUnitTests::test_student_creation
```

### **Coverage Testing:**
```bash
# Run with coverage
docker-compose exec api pytest billing/tests.py --cov=billing --cov-report=term

# Generate HTML coverage report
docker-compose exec api pytest billing/tests.py --cov=billing --cov-report=html

# View coverage report
open htmlcov/index.html  # (from your host machine)
```

### **Testing Specific Areas:**
```bash
# Test only unit tests
docker-compose exec api pytest billing/tests.py::BillingUnitTests

# Test only API tests
docker-compose exec api pytest billing/tests.py::BillingAPITests

# Test with specific markers
docker-compose exec api pytest billing/tests.py -m unit
```

## 🎯 **Benefits of Docker-First Testing**

1. **Consistent Environment**: Same Python version, same dependencies
2. **Team Consistency**: Everyone runs tests the same way
3. **No Local Conflicts**: No virtual environment issues
4. **Easy CI/CD**: Same commands work in production
5. **Database Access**: Tests can use the same database setup

## 🚨 **Important Notes**

- **Don't use local virtual environment** - It breaks your team workflow
- **Always test inside Docker** - Keeps everything consistent
- **Coverage reports are generated inside container** - Access via volumes
- **Database is shared** - Tests use the same database as development

## 🔍 **Troubleshooting**

### **If tests fail:**
```bash
# Check container logs
docker-compose logs api

# Rebuild if dependencies changed
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### **If coverage reports don't appear:**
```bash
# Check if htmlcov directory exists
docker-compose exec api ls -la

# Generate coverage report
docker-compose exec api pytest billing/tests.py --cov=billing --cov-report=html
```

## 📞 **Quick Reference**

```bash
# Start development
cd maple_key_music_academy_docker
docker-compose up -d

# Run tests
docker-compose exec api pytest billing/tests.py --cov=billing --cov-report=html

# View coverage
open htmlcov/index.html
```

---

**This approach respects your existing Docker workflow while adding comprehensive testing! 🎵**
