Die League - Fixed App

1) Create DB and load schema (XAMPP shell):
   "C:\xampp\mysql\bin\mysql.exe" -h 127.0.0.1 -u root -e "CREATE DATABASE IF NOT EXISTS die_league_db CHARACTER SET utf8mb4;"
   "C:\xampp\mysql\bin\mysql.exe" -h 127.0.0.1 -u root die_league_db < Milestone2.sql
   "C:\xampp\mysql\bin\mysql.exe" -h 127.0.0.1 -u root die_league_db < security.sql

2) Python env (Command Prompt):
   cd /d C:\path\to\die_league_app
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt

3) Configure .env then run:
   python app.py

4) Open http://127.0.0.1:5000/
