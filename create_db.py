# C:\projects\league-manager-api\create_db.py

import mysql.connector
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Configuration (Maintenance Mode) ---
# We force ROOT here because 'league_app' is not allowed to DROP databases.
DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_USER = "root"    # Force Administrator
DB_PASSWORD = ""    # XAMPP default is empty
DB_NAME = "die_league_db"
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

# C:\projects\league-manager-api\create_db.py (REPLACE execute_sql_file ENTIRELY)

def execute_sql_file(conn, file_path):
    """
    Reads a SQL file and executes statements. Uses custom logic to correctly parse
    and execute stored procedures that use the DELIMITER command.
    """
    print(f"Reading SQL from {file_path}...")
    
    with open(file_path, 'r') as f:
        sql_script = f.read()
    
    cursor = conn.cursor()
    executed_count = 0
    
    # Custom parser state variables
    commands = []
    current_command = []
    current_delimiter = ';'
    
    # 1. Use the script's content to process commands
    # We use the native Python split based on the content of the file
    
    # Process the entire script content line by line, splitting by the command delimiter
    # This loop is designed to handle the DELIMITER changes effectively
    for line in sql_script.split('\n'):
        clean_line = line.strip()
        if not clean_line or clean_line.startswith('--'):
            continue

        # Check for DELIMITER change command
        if clean_line.upper().startswith('DELIMITER'):
            # Switch the delimiter
            current_delimiter = clean_line.split()[1]
            continue
        
        # Add line to the current command buffer
        current_command.append(line)
        
        # Check if the command buffer ends with the current delimiter
        if current_command[-1].strip().endswith(current_delimiter):
            
            # The full command is ready (multi-line)
            command_text = ' '.join(current_command).strip()
            
            # Remove the trailing delimiter
            if command_text.endswith(current_delimiter):
                command_text = command_text[:-len(current_delimiter)].strip()
            
            if command_text:
                commands.append(command_text)
            
            # Reset buffer
            current_command = []

    # --- Execute Commands ---
    for command in commands:
        if not command:
            continue
            
        try:
            # We must execute the command here. For procedures, this is the whole block.
            # For standard DDL, it's one statement.
            cursor.execute(command)

            executed_count += 1
            
            # If the command was a stored procedure call or DECLARE, 
            # we need to consume any result sets, even if none are explicitly returned.
            # This is the tricky part that 'Commands out of sync' complains about.
            # We safely consume all available results before sending the next command.
            # (Note: This is often complex and depends on the specific connector's API.)
            
            # We rely on the connection being stable, if it throws "commands out of sync"
            # we must process the results. We try to use get_result() if available.
            try:
                # Check for results, especially after procedural code
                while cursor.nextset():
                    pass
            except Exception:
                # This is a fallback to ensure we move past the current statement's result set
                pass
            
        except mysql.connector.Error as err:
            print(f"\nSQL Execution Error on command: {command[:80]}...")
            print(f" Error: {err.msg}")
            conn.rollback()
            raise Exception(f"FATAL SQL ERROR: {err.msg}") from err
            
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