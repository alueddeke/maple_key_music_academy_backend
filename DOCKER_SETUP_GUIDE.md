# Docker + Nginx Setup Guide for Separate Repos

This guide shows you how to implement the Docker + Nginx architecture from the RiskTec project for a Django/React setup with separate repositories.

## 🏗️ Architecture Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Your Backend  │    │  Your Frontend  │    │   Orchestrator  │
│     Repo        │    │      Repo       │    │      Repo       │
│   (Django)      │    │   (React/Vite)  │    │  (Docker Setup) │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌─────────────────┐
                    │  Docker Compose │
                    │   Orchestrates  │
                    │   Everything    │
                    └─────────────────┘
```

## 📁 Project Structure

### 1. Create Orchestrator Repository
```
your-project-docker/
├── docker-compose.yaml
├── docker-compose.prod.yaml
├── nginx/
│   ├── Dockerfile.dev
│   └── default.conf
├── .envs/
│   ├── env.dev
│   └── env.prod
├── scripts/
│   ├── setup.sh
│   └── deploy.sh
└── README.md
```

### 2. Your Existing Repos
```
your-backend-repo/          # Your existing Django repo
├── Dockerfile              # Add this
├── requirements.txt        # Already exists
├── manage.py              # Already exists
└── ...

your-frontend-repo/         # Your existing React/Vite repo
├── Dockerfile              # Add this
├── package.json           # Already exists
└── ...
```

## 🚀 Implementation Steps

### Step 1: Set Up Orchestrator Repository

1. **Create new repository** called `your-project-docker`
2. **Clone your existing repos** as siblings:
   ```bash
   mkdir your-project-workspace
   cd your-project-workspace
   
   git clone https://github.com/your-org/your-backend-repo.git
   git clone https://github.com/your-org/your-frontend-repo.git
   git clone https://github.com/your-org/your-project-docker.git
   ```

3. **Your workspace structure should look like:**
   ```
   your-project-workspace/
   ├── your-backend-repo/
   ├── your-frontend-repo/
   └── your-project-docker/
   ```

### Step 2: Add Dockerfiles to Your Repos

#### Backend Repository (`your-backend-repo/Dockerfile`)
```dockerfile
FROM python:3.11-bookworm

ENV PYTHONUNBUFFERED 1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get -y update && apt-get -y upgrade
RUN apt-get -y install \
    postgresql \
    postgresql-contrib \
    build-essential

WORKDIR /usr/app

COPY requirements.txt ./
RUN pip3 install --upgrade pip setuptools wheel
RUN pip3 install -r requirements.txt
RUN pip3 install psycopg2-binary --no-binary psycopg2-binary

COPY . ./

RUN useradd admin
RUN chown -R admin:admin ./
USER admin

EXPOSE 8000
CMD ["python3", "manage.py", "runserver", "0.0.0.0:8000"]
```

#### Frontend Repository (`your-frontend-repo/Dockerfile`)
```dockerfile
FROM node:19-alpine as dependencies

WORKDIR /usr/app
COPY package*.json ./
COPY pnpm-lock.yaml ./
RUN corepack enable pnpm && pnpm install --frozen-lockfile

FROM node:19-alpine as development
WORKDIR /usr/app

COPY --from=dependencies /usr/app/node_modules ./node_modules
COPY --from=dependencies /usr/app/package*.json ./

ENV NODE_ENV=development
ENV NODE_OPTIONS="--max-old-space-size=4096"
ENV WATCHPACK_POLLING=true
ENV FAST_REFRESH=true
ENV VITE_STRICT_MODE=true

EXPOSE 3000
CMD ["pnpm", "dev"]
```

### Step 3: Create Orchestrator Files

#### Docker Compose (`your-project-docker/docker-compose.yaml`)
```yaml
version: '3.8'

services:
  db:
    image: postgres:13.7
    container_name: your-project-db
    env_file:
      - ./.envs/env.dev
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $POSTGRES_USER -d $POSTGRES_DB"]
      interval: 5s
      timeout: 5s
      retries: 5

  nginx:
    build:
      context: nginx
      dockerfile: Dockerfile.dev
    restart: always
    container_name: your-project-nginx
    ports:
      - "8000:80"
    depends_on:
      - api
      - frontend

  api:
    build:
      context: ../your-backend-repo
      dockerfile: Dockerfile
    container_name: your-project-api
    env_file:
      - ./.envs/env.dev
    volumes:
      - ../your-backend-repo:/usr/app/
    depends_on:
      db:
        condition: service_healthy
    entrypoint: |
      bash -c "
      python3 manage.py migrate --no-input && 
      python3 manage.py collectstatic --noinput &&
      python3 manage.py runserver 0.0.0.0:8000"

  frontend:
    build:
      context: ../your-frontend-repo
      dockerfile: Dockerfile
    container_name: your-project-frontend
    environment:
      - NODE_ENV=development
      - NEXT_PUBLIC_API_URL=http://localhost:8000/api
      - WATCHPACK_POLLING=true
      - FAST_REFRESH=true
    volumes:
      - ../your-frontend-repo:/usr/app
      - node_modules:/usr/app/node_modules
      - next_cache:/usr/app/.next/cache

volumes:
  postgres_data:
  node_modules:
  next_cache:
```

#### Nginx Configuration (`your-project-docker/nginx/default.conf`)
```nginx
upstream api {
    server api:8000;
}

upstream frontend {
    server frontend:3000;
}

server {
    listen 80;
    server_name localhost;

    # Frontend routes (React/Vite)
    location / {
        proxy_pass http://frontend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_connect_timeout 600s;
        proxy_send_timeout 600s;
    }

    # API routes (Django)
    location ~ ^/(api|admin|static|media|docs|schema) {
        proxy_pass http://api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_connect_timeout 600s;
        proxy_send_timeout 600s;
    }

    # WebSocket support for React/Vite hot reloading
    location ~ ^/(ws|_next) {
        proxy_pass http://frontend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### Nginx Dockerfile (`your-project-docker/nginx/Dockerfile.dev`)
```dockerfile
FROM nginx
COPY ./default.conf /etc/nginx/conf.d/default.conf
```

#### Environment File (`your-project-docker/.envs/env.dev`)
```env
# Database Configuration
POSTGRES_DB=your_project_db
POSTGRES_USER=your_user
POSTGRES_PASSWORD=your_password
POSTGRES_HOST=db

# Django Configuration
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,api,nginx,127.0.0.1

# Database URL for Django
DATABASE_URL=postgresql://your_user:your_password@db:5432/your_project_db

# React/Vite Configuration
VITE_API_URL=http://localhost:8000/api
```

## 🎯 Usage

### Development
```bash
# From your-project-docker directory
cd your-project-docker
docker compose up --build
```

### Access Your Application
- **Frontend**: http://localhost:8000
- **API**: http://localhost:8000/api
- **Admin**: http://localhost:8000/admin
- **Database**: localhost:5432

### Useful Commands
```bash
# View logs
docker compose logs -f

# Stop services
docker compose down

# Rebuild specific service
docker compose up --build api

# Access database
docker compose exec db psql -U your_user -d your_project_db
```

## 🔧 Customization

### Update Repository Paths
In `docker-compose.yaml`, update these lines to match your repo names:
```yaml
api:
  build:
    context: ../your-backend-repo  # Change this
    dockerfile: Dockerfile

frontend:
  build:
    context: ../your-frontend-repo  # Change this
    dockerfile: Dockerfile
```

### Update Environment Variables
Modify `.envs/env.dev` with your specific configuration:
- Database credentials
- Django secret key
- API URLs
- Any other environment-specific settings

### Update Nginx Routes
In `nginx/default.conf`, modify the location blocks to match your API structure:
```nginx
# If your API is at /backend instead of /api
location ~ ^/(backend|admin|static|media|docs|schema) {
    proxy_pass http://api;
}
```

## 🚀 Benefits of This Setup

1. **Team Independence**: Frontend and backend teams can work separately
2. **Easy Onboarding**: New developers just need `docker compose up`
3. **Consistent Environments**: Same setup everywhere
4. **Production Ready**: Easy to deploy with minimal changes
5. **Hot Reloading**: Code changes reflect immediately
6. **No CORS Issues**: Nginx handles routing seamlessly

## 🆚 Monorepo vs Separate Repos

| Aspect | Monorepo | Separate Repos + Orchestrator |
|--------|----------|-------------------------------|
| **Team Independence** | ❌ Shared codebase | ✅ Independent development |
| **Release Cycles** | ❌ Coupled releases | ✅ Independent releases |
| **CI/CD Complexity** | ✅ Simple | ⚠️ Multiple pipelines |
| **Onboarding** | ✅ Single repo | ⚠️ Multiple repos |
| **Technology Flexibility** | ❌ Hard to change | ✅ Easy to swap services |
| **Docker Setup** | ✅ Simple paths | ⚠️ Relative paths |

## 🎉 You're Ready!

This setup gives you all the benefits of the RiskTec project's Docker architecture while maintaining the flexibility of separate repositories. Your teams can work independently while still having a unified development and deployment experience.
