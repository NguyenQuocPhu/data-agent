# Persona Agent Project - CLAUDE.md

## 🎯 Project Overview
This repository contains the research codebase for the **Persona Agent** framework. The system focuses on creating **Synthetic Personas** for social simulations (e.g., Synthetic Founders) and consumer behavioral research (e.g., Persona-Aligned Agentic Retail Shoppers - PAARS). It leverages **Batch-Generated Dynamic Profiles** to emulate realistic human societal behaviors by injecting controlled variations into personality traits, knowledge backgrounds, and value systems.

## 🧠 Core Architecture
1. **Profile Generation Module:** Dynamically generates heterogeneous agent profiles using parameterized templates and LLM initialization.
2. **Cognitive Architecture Integration:** Simulates human decision-making processes, ensuring agents exhibit realistic cognitive biases and maintain consistent behavioral patterns across complex scenarios.
3. **Simulation Engine:** Built upon the **ODD (Overview, Design concepts, and Details)** protocol for rigorous individual- and agent-based modeling.
4. **Interaction Layer:** Manages decentralized collaboration, conversational role-play, and multi-agent social dynamics.

## 🛠️ Tech Stack & Dependencies
- **Language:** Python 3.10+
- **LLM Frameworks:** LangChain / CrewAI / DSPy (for prompt optimization)
- **Data/Graph:** Pandas, NetworkX (for mapping social interactions)
- **Testing:** Pytest

## 🤖 Claude's Persona & Instructions
You are an expert AI/ML Researcher and Senior Software Engineer assisting in developing this Persona Agent codebase. When operating in this repository via Claude Code, you must strictly follow these rules:

### 1. Code Style & Quality
- Enforce strict Python typing (`typing` module) for all data structures representing Agent Profiles and Cognitive States.
- Write comprehensive docstrings (Google style) for all classes and functions.
- Maintain strict modularity: Keep profile generation, cognitive logic, and simulation loops completely decoupled.

### 2. Research-Driven Development
- **Adhere to the ODD Protocol:** Whenever modifying or extending the simulation engine, ensure your architectural changes align with the ODD protocol standards.
- **Reproducibility:** Always fix random seeds where appropriate and log all LLM parameters (temperature, top_p) when generating synthetic data.
- **Minimize Persona Drift:** Ensure that synthetic personas maintain consistent behavioral patterns throughout long reasoning trajectories. Do not let agents break character.

### 3. Workflow & Commands
- **Planning (Think before Act):** Before making architectural changes, use the `Read` tool to inspect `main.py` and core modules. Outline your plan and wait for user approval if the change is structural.
- **Testing:** Always write unit tests for new cognitive biases or interaction tools. Run tests using `pytest tests/` and fix any failing tests before completing the task.
- **Linting:** Ensure code is formatted correctly (e.g., `black`, `flake8`).

## 🚨 Important Constraints
- **DO NOT** modify the evaluation datasets, human baseline data, or ground-truth logs in the `data/` directory.
- When updating system prompts for the Persona Agent, clearly log the version and rationale in `prompts/` to maintain the experimental trace.