# Project Structure

Below is an illustration of the directory tree for the **TeleSpace** project, along with a brief description of the function of each file and folder:

```
TeleSpace/
├── api/                            # Application Programming Interface (FastAPI) for external system interaction
│   ├── routers/                    # Definition of API endpoints
│   │   ├── auth.py                 # Authentication and login routes
│   │   ├── explorer.py             # File and folder exploration routes
│   │   ├── items.py                # Item management routes (create, delete, update)
│   │   ├── share.py                # File and link sharing routes
│   │   └── structure.py            # Folder structure and organization management routes
│   ├── dependencies.py             # Shared dependencies (e.g., token validation and database sessions)
│   ├── main.py                     # Entry point for the API application and server startup
│   └── schemas.py                  # Data models (Pydantic Models) for input/output validation
│
├── app/                            # Main application source code
│   ├── bot/                        # Telegram bot code
│   │   ├── handlers/               # Event handlers and bot commands
│   │   │   ├── admin.py            # Admin commands and dashboard
│   │   │   ├── automation.py       # Automation handlers and scheduled tasks
│   │   │   ├── main_menu.py        # Main menu handlers and initial interaction
│   │   │   ├── navigation.py       # Navigation logic between folders and menus
│   │   │   ├── router.py           # Main router for distributing updates to appropriate handlers
│   │   │   ├── upload.py           # Handling file upload and storage processes
│   │   │   └── user_updates.py     # Handling user data and settings updates
│   │   ├── keyboards.py            # Definition of keyboards (buttons) and interactive menus
│   │   ├── main.py                 # Bot startup point and `ApplicationBuilder` initialization
│   │   ├── processors.py           # Logic for processing messages and files before storage or display
│   │   └── utils.py                # General helper functions for the bot
│   │
│   └── shared/                     # Shared modules between the Bot and API
│       ├── database/               # Database interaction layer
│       │   ├── auth.py             # Database logic for authentication
│       │   ├── automation.py       # Database operations for automation
│       │   ├── containers.py       # Container logic (file/link storage)
│       │   ├── core.py             # Database connection setup and session management
│       │   ├── items.py            # Database operations for item management (files and folders)
│       │   ├── setup.py            # Scripts for initializing tables and initial data
│       │   └── users.py            # Database operations for user management
│       ├── ai.py                   # Artificial Intelligence integration (e.g., Google Gemini)
│       ├── config.py               # Loading and managing project settings and environment variables
│       └── constants.py            # Global project constants
│
├── static/                         # Static and locally stored files
│   ├── profiles/                   # User profile pictures
│   └── thumbnails/                 # Thumbnails for uploaded files
│
├── Dockerfile                      # Application runtime environment definition (Docker Image)
├── docker-compose.yml              # Services definition and container configuration (Docker Compose)
├── requirements.txt                # List of project libraries and dependencies (Python Dependencies)
└── README.md                       # General project documentation file
```