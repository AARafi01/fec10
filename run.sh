#!/bin/bash
# DU Crack Runner Script

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color
BOLD='\033[1m'

echo -e "${PURPLE}${BOLD}==================================================${NC}"
echo -e "${CYAN}${BOLD}                 DU CRACK SCRAPER                 ${NC}"
echo -e "${PURPLE}${BOLD}==================================================${NC}"
echo -e "${GREEN}✨ Activating virtual environment...${NC}"

# Check virtual environment
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}⚠️ Virtual environment (.venv) not found. Creating it...${NC}"
    python3 -m venv .venv
    echo -e "${GREEN}✨ Virtual environment created successfully.${NC}"
fi

# Activate virtual environment
source .venv/bin/activate

# Install dependencies if requested
if [ "$1" == "--install" ] || [ "$1" == "-i" ]; then
    echo -e "${GREEN}📦 Installing / Upgrading dependencies...${NC}"
    pip install -r requirements.txt
fi

echo -e "${GREEN}🚀 Starting Flask Application...${NC}"
echo -e "${BLUE}🔗 Home Page:   ${BOLD}http://localhost:5000${NC}"
echo -e "${BLUE}🔗 Admin Panel: ${BOLD}http://localhost:5000/admin${NC}"
echo -e "${YELLOW}🛑 Press Ctrl+C to stop the application${NC}"
echo -e "${PURPLE}${BOLD}==================================================${NC}"
echo ""
python index.py
