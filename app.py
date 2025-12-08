import os
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import mysql.connector
from flask import request, session

load_dotenv()

app = Flask(__name__)
CORS(app,
     supports_credentials=True,
     resources={r"/*": {"origins": ["http://localhost:5500", "http://127.0.0.1:5500", "null"]}},
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])

@app.route('/api/auth/register', methods=['POST'])
def register():
    return jsonify({"message": "OK"}), 200


app.secret_key = "super_secret_key"  # required for session
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"] = False  # set True in HTTPS


def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME")
        )
        return conn
    except mysql.connector.Error as err:
        print(f"Database connection error: {err}")
        return None
    
# app.py (Define this near the top, after your imports)
from functools import wraps

def login_required(f):
    """Decorator to check if a user is logged into the session."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session or not session.get('logged_in'):
            return jsonify({"error": "Authorization required"}), 401
        return f(*args, **kwargs)
    return decorated_function

# app.py (Define this near the top, after imports)

def role_required(required_role):
    """Decorator to check if a user has a specific role for the league."""
    def decorator(f):
        @wraps(f)
        @login_required # Ensure user is logged in first
        def wrapper(*args, **kwargs):
            user_id = session.get('user_id')
            league_id = kwargs.get('league_id') or request.json.get('league_id')
            
            if not league_id:
                return jsonify({"error": "League ID is required for this operation"}), 400

            conn = get_db_connection()
            if not conn:
                return jsonify({"error": "Database connection failed"}), 500
            
            cursor = conn.cursor()
            is_authorized = False

            try:
                # Check if the user has the required role for the given league
                query = "SELECT COUNT(*) FROM RoleAssignment WHERE user_id = %s AND league_id = %s AND role = %s"
                cursor.execute(query, (user_id, league_id, required_role))
                if cursor.fetchone()[0] > 0:
                    is_authorized = True

            except mysql.connector.Error as err:
                print(f"RBAC check error: {err}")
            finally:
                cursor.close()
                conn.close()

            if is_authorized:
                return f(*args, **kwargs)
            else:
                return jsonify({"error": f"Permission denied. Role '{required_role}' required."}), 403
        return wrapper
    return decorator


# app.py (Add this function)

@app.route('/api/teams', methods=['POST'])
@role_required('Commissioner') # Only Commissioner can add a new team
def create_team():
    """Adds a new team to a specified league, requires Commissioner role."""
    data = request.get_json()
    league_id = data.get('league_id')
    team_name = data.get('team_name')

    if not all([league_id, team_name]):
        return jsonify({"error": "Missing league_id or team_name"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    
    try:
        # Check if the team name is already taken in that league (UNIQUE constraint protection)
        query = "INSERT INTO Team (league_id, team_name) VALUES (%s, %s)"
        cursor.execute(query, (league_id, team_name))
        conn.commit()
        
        team_id = cursor.lastrowid
        
        return jsonify({"message": "Team created successfully", "team_id": team_id}), 201

    except mysql.connector.Error as err:
        if err.errno == 1062: # Duplicate entry error
             return jsonify({"error": f"Team name '{team_name}' already exists in this league."}), 409
        print(f"Database error during team creation: {err}")
        return jsonify({"error": "Team creation failed due to server error"}), 500
    finally:
        cursor.close()
        conn.close()

# -----------------------
# ROUTES MUST BE ABOVE HERE
# -----------------------

@app.route('/api/status', methods=['GET'])
def status():
    conn = get_db_connection()
    if conn and conn.is_connected():
        conn.close()
        return jsonify({"status": "API running", "db_status": "Connected"}), 200
    else:
        return jsonify({"status": "API running", "db_status": "Failed to connect"}), 500

# app.py (Modify the existing route)

@app.route('/api/league', methods=['GET'])
@login_required # <-- NEW: Only logged-in users can access this now
def get_leagues():
    """Retrieves all league information."""
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    leagues = []
    cursor = conn.cursor(dictionary=True)

    try:
        # We will update this query in Step 2 to filter by user role!
        query = "SELECT league_id, name, season_year, status FROM League ORDER BY season_year DESC, name ASC"
        cursor.execute(query)
        leagues = cursor.fetchall()
        return jsonify(leagues), 200
    except mysql.connector.Error as err:
        return jsonify({"error": f"Error executing query: {err}"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/sitemap', methods=['GET'])
def sitemap():
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            "endpoint": rule.endpoint,
            "methods": list(rule.methods),
            "url": rule.rule
        })
    return jsonify(routes), 200



@app.route('/api/auth/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == "OPTIONS":
        return '', 204   # allow preflight success

    data = request.get_json() or {}
    email = data.get("email")
    password = data.get("password")

    # Temporary success response (replace with real logic)
    return jsonify({"message": "Login OK", "email": email}), 200


# -----------------------
# NOTHING SHOULD BE BELOW HERE EXCEPT THIS
# -----------------------

if __name__ == '__main__':
    app.run(debug=True)
