# C:\projects\league-manager-api\create_db.py

import mysql.connector
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Configuration (Copied from .env and app.py logic) ---
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "die_league_db")
SCHEMA_FILE = "db/schema.sql"  # Assuming you placed schema.sql in a 'db' folder

def get_admin_connection():
    """
    Establishes a connection to the MySQL server without specifying the database name.
    This is required to run CREATE DATABASE or DROP DATABASE statements.
    """
    try:
        cfg = {
            "host": DB_HOST,
            "user": DB_USER,
            "password": DB_PASSWORD,
            "port": DB_PORT,
        }
        
        # Optionally handle auth_plugin if present
        ap = os.getenv("DB_AUTH_PLUGIN")
        if ap:
            cfg["auth_plugin"] = ap
            
        print(f"Attempting to connect to MySQL server at {DB_HOST}:{DB_PORT} as user {DB_USER}...")
        return mysql.connector.connect(**cfg)
    except mysql.connector.Error as err:
        print("="*60)
        print("DATABASE CONNECTION FAILED")
        print(f"Error: {err.msg}")
        print("Please check your DB_HOST, DB_PORT, DB_USER, and DB_PASSWORD in your .env file.")
        print("Ensure the MySQL server is running and accessible.")
        print("="*60)
        return None


# C:\projects\league-manager-api\create_db.py

def execute_sql_file(conn, file_path):
    """
    Reads a SQL file, cleans the content, and executes each statement 
    individually to ensure the DDL is applied correctly.
    """
    print(f"Reading SQL from {file_path}...")
    
    with open(file_path, 'r') as f:
        sql_content = f.read()
    
    # --- Robust Cleanup and Splitting ---
    # 1. Remove comments
    lines = sql_content.split('\n')
    clean_lines = []
    for line in lines:
        if line.strip() and not line.strip().startswith('--'):
            clean_lines.append(line)
    
    # 2. Join lines back, then split by semicolon
    sql_commands = ' '.join(clean_lines).split(';')
    
    # 3. Filter and clean up individual commands
    final_commands = [c.strip() for c in sql_commands if c.strip()]
    # ------------------------------------

    cursor = conn.cursor()
    executed_count = 0
    
    for command in final_commands:
        try:
            # Check for empty command strings after cleanup
            if command:
                cursor.execute(command)
                executed_count += 1
        except mysql.connector.Error as err:
            # If a statement fails, print the error and stop the process
            print(f"SQL Execution Error on command: {command[:80]}...")
            print(f" Error: {err.msg}")
            conn.rollback()
            raise 
    
    conn.commit()
    cursor.close()
    print(f"{executed_count} SQL statements executed.")


def create_and_seed_database():
    """
    Drops existing database, creates a new one, and builds the schema.
    """
    admin_conn = get_admin_connection()
    if admin_conn is None:
        return

    admin_cursor = admin_conn.cursor()

    try:
        # 1. Drop existing database
        print(f"\nDropping database '{DB_NAME}' if it exists...")
        admin_cursor.execute(f"DROP DATABASE IF EXISTS {DB_NAME}")
        
        # 2. Create database
        print(f"Creating database '{DB_NAME}'...")
        admin_cursor.execute(f"CREATE DATABASE {DB_NAME}")
        admin_conn.commit()
        
        # 3. Connect to the new database
        admin_conn.close()
        
        # Reconnect with the new database selected
        cfg = {
            "host": DB_HOST,
            "user": DB_USER,
            "password": DB_PASSWORD,
            "database": DB_NAME,
            "port": DB_PORT,
        }
        db_conn = mysql.connector.connect(**cfg)
        
        # 4. Execute schema DDL
        execute_sql_file(db_conn, SCHEMA_FILE)

        # 5. Create a standard app_user (for more secure connection in app.py logic)
        # Note: This is optional, but aligns with your app.py security logic.
        print("\nCreating standard application user 'app_user'...")
        try:
             # FLASK_SECRET is not secure for this. Let's use a placeholder or read a dedicated variable.
             # Since you had 'app_pw_123' hardcoded in app.py, we'll create the user with a generic password.
            
            # Flush privileges before running CREATE USER to ensure it works properly
            admin_conn = get_admin_connection()
            if admin_conn:
                cursor = admin_conn.cursor()
                cursor.execute("FLUSH PRIVILEGES")
                admin_conn.commit()
                cursor.close()
                admin_conn.close()

            db_conn_admin = get_admin_connection()
            cursor = db_conn_admin.cursor()
            
            # Ensure the user doesn't exist
            cursor.execute("DROP USER IF EXISTS 'app_user'@'%'")
            db_conn_admin.commit()
            
            # Create user and grant permissions
            cursor.execute("CREATE USER 'app_user'@'%' IDENTIFIED BY 'app_pw_123'")
            cursor.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {DB_NAME}.* TO 'app_user'@'%'")
            cursor.execute("FLUSH PRIVILEGES")
            db_conn_admin.commit()
            cursor.close()
            db_conn_admin.close()
            print("Application user 'app_user' created and granted permissions.")
            
        except mysql.connector.Error as err:
            print(f"Could not create 'app_user' (run manually if needed): {err.msg}")

        print("\n-------------------------------------------")
        print(f"Database '{DB_NAME}' created and schema applied successfully!")
        print("-------------------------------------------")

    except Exception as e:
        print(f"\n FATAL ERROR DURING DATABASE SETUP: {e}")
        
    finally:
        if 'db_conn' in locals() and db_conn.is_connected():
            db_conn.close()
        if admin_conn.is_connected():
            admin_conn.close()

if __name__ == '__main__':
    create_and_seed_database()