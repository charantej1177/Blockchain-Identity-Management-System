# Blockchain-Enabled Digital Identity and Access Management System

This is a full-stack web application built for managing digital identities using Ethereum Blockchain and Flask.

## Tech Stack
- Frontend: HTML5, CSS3, Bootstrap 5
- Backend: Python Flask
- Database: MySQL
- Blockchain: Solidity, Web3.py, Ganache

## Setup Instructions

1. Install Python packages:
   ```bash
   pip install -r requirements.txt
   ```

2. Setup MySQL database:
   Run the queries in `database/schema.sql` in your MySQL server.

3. Update `config.py`:
   Ensure your MySQL username and password are correct.

4. Run Ganache locally and update `WEB3_PROVIDER_URI` if necessary.

5. Run the application:
   ```bash
   python app.py
   ```
