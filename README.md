# DACL Enhanced Agent

**DACL (Deterministic AI Contract Logic) Enhanced Agent** is a powerful system providing robust deterministic evaluation for enterprise workflows. It combines a FastAPI backend, an LLM-driven intelligence layer utilizing Azure OpenAI, a React Vite frontend, and a Model Context Protocol (MCP) server for easy tool integration.

## 🚀 Features
- **Deterministic AI Contract Logic**: Evaluates complex workflows using a Rete-based rule engine.
- **MCP Server Integration**: Exposes the workflow logic through the Model Context Protocol, enabling direct interaction with Agentic frameworks.
- **FastAPI Backend**: Fast and robust API endpoints with JWT-based authentication.
- **Interactive UI**: A modern React frontend for managing policies and rules testing.
- **LangSmith Tracing**: Integrated observability and tracing for LLM activities.

---

## 🛠️ Prerequisites

- **Python 3.12+** (configured with [uv](https://github.com/astral-sh/uv) for fast package management)
- **Node.js 18+** (for frontend development)
- **Docker & Docker Compose** (for containerized deployment)

---

## 💻 Local Development Setup

### 1. Clone the repository
```bash
git clone <repository_url>
cd dacl_agent
```

### 2. Environment Configuration
Copy the sample environment file and fill in your secrets.
```bash
cp .env.example .env
```
Edit `.env` to include your valid Azure OpenAI keys, LangSmith keys, and JWT secrets.

### 3. Backend Setup
We use `uv` for lightning-fast Python package management.
```bash
uv venv
# Activate virtual environment
# Windows:
.venv\Scripts\activate
# Unix/macOS:
source .venv/bin/activate

# Install dependencies
uv pip install -e .
```
Start the FastAPI server:
```bash
uv run uvicorn src.dacl_agent.main:app --reload
```
*Backend will be running on [http://localhost:8000](http://localhost:8000)*

### 4. Frontend Setup
Open a new terminal and navigate to the frontend directory:
```bash
cd frontend
npm install
npm run dev
```
*Frontend will typically be running on [http://localhost:5173](http://localhost:5173)*

---

## 🐳 Docker Deployment

To spin up the entire stack (Backend, Frontend, and MCP Server) using Docker Compose:

```bash
docker-compose up -d --build
```

This will expose the following services:
- **Backend API**: `http://localhost:8000`
- **Frontend Dashboard**: `http://localhost:3000`
- **MCP Server**: `http://localhost:8080`

---

## 🔌 Model Context Protocol (MCP)

The DACL Agent includes an extensive **MCP Server** implementation allowing external Agentic workflows (Claude, Tagent, HR Agents) to programmatically interface with the deterministic rules engine. 

For complete documentation on MCP setup, configuration, available tools (like smart intent routing), resources, and prompts, please see the **[MCP Documentation](./MCP_README.md)**.

---

## 🧪 Running Tests
To ensure everything is working correctly, you can run the test script:
```bash
python test_mcp.py
```
