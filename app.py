import os
import mysql.connector
from flask import Flask, jsonify, send_file, make_response, request, session, redirect, url_for
from flask_cors import CORS
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
from functools import wraps
from datetime import datetime
# Removed unused imports: csv, json, io, BytesIO, g, Blueprint, datetime

load_dotenv()

app = Flask(__name__)
bcrypt = Bcrypt(app)
CORS(app,
     supports_credentials=True,
     resources={r"/*": {"origins": ["http://localhost:5500", "http://127.0.0.1:5500", "null"]}},
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])

app.secret_key = os.getenv("FLASK_SECRET", "super_secret_key")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True

# --- DATABASE CONNECTION ---

def get_db_connection():
    try:
        use_secure = os.getenv("USE_SECURE_DB", "false").lower() == "true"
        
        cfg = {}
        
        if use_secure:
            # Production - use limited privilege user
            cfg = {
                "host": os.getenv("DB_HOST", "127.0.0.1"),
                "user": "app_user",
                "password": "app_pw_123",
                "database": os.getenv("DB_NAME", "die_league_db"),
                "port": int(os.getenv("DB_PORT", "3306")),
            }
        else:
            # Development - use root or dev user
            cfg = {
                "host": os.getenv("DB_HOST", "127.0.0.1"),
                "user": os.getenv("DB_USER", "root"),
                "password": os.getenv("DB_PASSWORD", ""),
                "database": os.getenv("DB_NAME", "die_league_db"),
                "port": int(os.getenv("DB_PORT", "3306")),
            }
        
        ap = os.getenv("DB_AUTH_PLUGIN")
        if ap:
            cfg["auth_plugin"] = ap
        
        return mysql.connector.connect(**cfg)
    except mysql.connector.Error as err:
        print(f"Database connection error: {err}")
        return None

# --- DECORATORS (DEFINED BEFORE FIRST USAGE) ---

def login_required(f):
    """Decorator to check if a user is logged into the session."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session or not session.get('logged_in'):
            return jsonify({"error": "Authorization required"}), 401
        return f(*args, **kwargs)
    return decorated_function

def role_required(required_role):
    """Decorator to check if a user has a specific role for the league."""
    def decorator(f):
        @wraps(f)
        @login_required
        def wrapper(*args, **kwargs):
            user_id = session.get('user_id')
            league_id = kwargs.get('league_id') or request.json.get('league_id') if request.json else None
            
            if not league_id:
                league_id = request.args.get('league_id')
            
            if not league_id:
                return jsonify({"error": "League ID is required for this operation"}), 400

            conn = get_db_connection()
            if not conn:
                return jsonify({"error": "Database connection failed"}), 500
            
            cursor = conn.cursor()
            is_authorized = False

            try:
                # FIX: RoleAssignment -> role_assignment
                query = "SELECT COUNT(*) FROM role_assignment WHERE user_id = %s AND league_id = %s AND role = %s"
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

# --- CORE ROUTING ---

@app.route('/', methods=['GET'])
@app.route('/login', methods=['GET'])
def serve_login_page():
    """Serves the static index.html (login page)."""
    return send_file('static/index.html')

@app.route('/leagues.html', methods=['GET'])
@login_required 
def serve_leagues_page():
    """Serves the leagues.html page only if the user is logged in."""
    return send_file('static/leagues.html')

# ==================== AUTH ENDPOINTS ====================

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')

    if not all([name, email, password]):
        return jsonify({"error": "Missing name, email, or password"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()

    try:
        # 1. Hashing the Password
        password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

        # 2. Insert into user_account
        user_query = "INSERT INTO user_account (name, email, password_hash) VALUES (%s, %s, %s)"
        cursor.execute(user_query, (name, email, password_hash))

        # 3. Prepare Name for Player Profile
        name_parts = name.split(' ')
        first_name = name_parts[0]
        last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''

        # 4. Insert Player Profile
        player_query = """
            INSERT INTO player (first_name, last_name, email)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
            first_name = VALUES(first_name),
            last_name = VALUES(last_name)
        """
        cursor.execute(player_query, (first_name, last_name, email))

        conn.commit()
        return jsonify({"message": "Registration successful. You can now log in."}), 201

    except mysql.connector.Error as err:
        conn.rollback()
        if err.errno == 1062:
            return jsonify({"error": "This email is already registered."}), 409
        print(f"Database error during registration: {err}") 
        return jsonify({"error": "Registration failed due to server error"}), 500
        
    except Exception as e:
        conn.rollback()
        print(f"CRITICAL PYTHON ERROR during registration: {e}")
        return jsonify({"error": "A critical server error occurred."}), 500
        
    finally:
        cursor.close()
        conn.close()

@app.route('/api/auth/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == "OPTIONS":
        return '', 204

    data = request.get_json() or {}
    email = data.get("email")
    password = data.get("password")

    if not all([email, password]):
        return jsonify({"error": "Missing email or password"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor(dictionary=True) 
    try:
        # FIX: UserAccount -> user_account
        query = "SELECT user_id, password_hash, name FROM user_account WHERE email = %s"
        cursor.execute(query, (email,))
        user = cursor.fetchone()

        if user and bcrypt.check_password_hash(user['password_hash'], password):
            session['logged_in'] = True
            session['user_id'] = user['user_id']
            session['email'] = email
            session['name'] = user['name']

            return jsonify({"message": "Login successful", "name": user['name'], "redirect_url": "/leagues.html"}), 200
        else:
            return jsonify({"error": "Invalid email or password"}), 401

    except mysql.connector.Error as err:
        print(f"Database error during login: {err}")
        return jsonify({"error": "Login failed due to server error"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """Clears the user session."""
    session.clear()
    return jsonify({"message": "Successfully logged out"}), 200


@app.route('/api/nav_content', methods=['GET'])
@login_required
def get_nav_content():
    """Dynamically generates the navigation bar content, including the user's name."""
    user_name = session.get('name', 'Guest')
    
    # We return the raw HTML string content here, including the user's name
    html_content = f"""
    <nav>
        <div class="nav-links">
            <a href="/leagues.html" style="font-weight: bold; text-decoration: none; color: white;">League Manager</a>
        </div>
        <div class="nav-auth">
            <span style="margin-right: 15px;">Logged in as: <strong>{user_name}</strong></span>
            <button id="logoutBtn">Logout</button>
        </div>
    </nav>
    """
    # Return the HTML string directly as a response
    return html_content, 200, {'Content-Type': 'text/html'}
# ==================== LEAGUE ENDPOINTS ====================

@app.route('/api/league', methods=['GET'])
@login_required
def get_leagues():
    """Retrieves leagues the logged-in user is associated with."""
    user_id = session.get('user_id')
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor(dictionary=True)

    try:
        query = """
            SELECT DISTINCT
                L.league_id,
                L.name,
                L.season_year,
                L.status,
                RA.role
            FROM
                league L                            
            JOIN
                role_assignment RA ON L.league_id = RA.league_id
            WHERE
                RA.user_id = %s
            ORDER BY
                L.season_year DESC, L.name ASC;
        """
        cursor.execute(query, (user_id,))
        leagues = cursor.fetchall()
        
        return jsonify(leagues), 200
        
    except mysql.connector.Error as err:
        return jsonify({"error": f"Error executing query: {err}"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/league', methods=['POST'])
@login_required
def create_league():
    """Creates a new league and assigns the creator as Commissioner."""
    data = request.get_json()
    league_name = data.get('name')
    # Get year from request, or default to current year (YYYY)
    season_year = data.get('season_year') or datetime.now().year 
    
    user_id = session.get('user_id')

    # Now, check for name and user_id, but the year will always be set
    if not all([league_name, user_id]): 
        return jsonify({"error": "Missing league name or user session data"}), 400
    
    # Ensure year is an integer, especially since it could come from datetime.now().year
    try:
        season_year = int(season_year)
    except ValueError:
        return jsonify({"error": "Season year must be a valid number."}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    
    try:
        # FIX: League -> league
        league_query = "INSERT INTO league (name, season_year, status) VALUES (%s, %s, 'Draft')"
        cursor.execute(league_query, (league_name, season_year))
        league_id = cursor.lastrowid
        
        # FIX: RoleAssignment -> role_assignment
        role_query = "INSERT INTO role_assignment (user_id, league_id, role) VALUES (%s, %s, %s)"
        cursor.execute(role_query, (user_id, league_id, 'Commissioner'))
        
        conn.commit()
        
        return jsonify({
            "message": f"League '{league_name} ({season_year})' created successfully.",
            "league_id": league_id
        }), 201

    except mysql.connector.Error as err:
        if err.errno == 1062:
            return jsonify({"error": f"A league named '{league_name}' already exists for season {season_year}."}), 409
        print(f"Database error during league creation: {err}")
        return jsonify({"error": "League creation failed due to server error"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/league/<int:league_id>', methods=['DELETE'])
@role_required('Commissioner')
def delete_league(league_id):
    """Deletes a league (Commissioner only)."""
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor()
    try:
        # FIX: League -> league
        cursor.execute("DELETE FROM league WHERE league_id = %s", (league_id,))
        
        if cursor.rowcount == 0:
            return jsonify({"error": "League not found"}), 404
        
        conn.commit()
        return jsonify({"message": "League deleted successfully"}), 200
        
    except mysql.connector.Error as err:
        print(f"Error deleting league: {err}")
        return jsonify({"error": "Failed to delete league"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/league/search', methods=['GET'])
@login_required
def search_leagues():
    """Search and filter leagues with sorting options."""
    search_term = request.args.get('q', '')
    season_year = request.args.get('year', '')
    sort_by = request.args.get('sort', 'year_desc') 

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor(dictionary=True)
    
    # FIX: League -> league
    query = "SELECT league_id, name, season_year, status FROM league WHERE 1=1 "
    params = []
    
    if search_term:
        query += "AND name LIKE %s "
        params.append(f"%{search_term}%")
    
    if season_year and season_year.isdigit():
        query += "AND season_year = %s "
        params.append(season_year)

    if sort_by == 'year_asc':
        query += "ORDER BY season_year ASC, name ASC"
    elif sort_by == 'name_asc':
        query += "ORDER BY name ASC, season_year DESC"
    elif sort_by == 'name_desc':
        query += "ORDER BY name DESC, season_year DESC"
    else: 
        query += "ORDER BY season_year DESC, name ASC"

    try:
        cursor.execute(query, tuple(params))
        leagues = cursor.fetchall()
        return jsonify(leagues), 200
        
    except mysql.connector.Error as err:
        return jsonify({"error": f"Error executing query: {err}"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/league/<int:league_id>/join', methods=['POST'])
@login_required
def join_league(league_id):
    """Assigns the logged-in user the 'Player' role in the specified league."""
    user_id = session.get('user_id')

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    
    try:
        # FIX: RoleAssignment -> role_assignment
        check_query = "SELECT role FROM role_assignment WHERE user_id = %s AND league_id = %s"
        cursor.execute(check_query, (user_id, league_id))
        if cursor.fetchone():
            return jsonify({"error": "You are already a member of this league."}), 409

        # FIX: RoleAssignment -> role_assignment
        role_query = "INSERT INTO role_assignment (user_id, league_id, role) VALUES (%s, %s, %s)"
        cursor.execute(role_query, (user_id, league_id, 'Player'))
        
        conn.commit()
        
        return jsonify({
            "message": f"Successfully joined league {league_id} as a Player.",
            "league_id": league_id
        }), 200

    except mysql.connector.Error as err:
        print(f"Database error during league join: {err}")
        return jsonify({"error": "Failed to join league due to server error"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/league.html', methods=['GET'])
@login_required 
def serve_league_detail_page():
    """Serves the league detail page for viewing specific leagues."""
    return send_file('static/league.html')

@app.route('/api/league/<int:league_id>/details', methods=['GET'])
@login_required
def get_league_details(league_id):
    """Get league details with teams."""
    current_user_id = session.get('user_id')

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        # FIX: RoleAssignment -> role_assignment
        role_query = "SELECT role FROM role_assignment WHERE user_id = %s AND league_id = %s"
        cursor.execute(role_query, (current_user_id, league_id))
        user_info = cursor.fetchone()

        if not user_info:
            return jsonify({"error": "User is not a member of this league"}), 403

        user_role = user_info['role']
        
        user_team_id = None
        
        # NOTE: Relying on email link since Player schema doesn't have P.user_id
        player_q = "SELECT player_id FROM player WHERE email = (SELECT email FROM user_account WHERE user_id = %s)"
        cursor.execute(player_q, (current_user_id,))
        player_row = cursor.fetchone()
        
        if player_row:
            player_id = player_row['player_id']
            # FIXES: team, team_membership
            team_check_query = f"""
                SELECT T.team_id
                FROM team T
                JOIN team_membership TM ON T.team_id = TM.team_id
                WHERE TM.player_id = {player_id} AND T.league_id = %s AND TM.active = TRUE
            """
            cursor.execute(team_check_query, (league_id,))
            team_row = cursor.fetchone()
            if team_row:
                user_team_id = team_row['team_id']
        
        # FIX: League -> league
        league_query = "SELECT name, season_year, status FROM league WHERE league_id = %s"
        cursor.execute(league_query, (league_id,))
        league = cursor.fetchone()
        if not league:
            return jsonify({"error": "League not found"}), 404

        # FIXES: team, team_membership
        teams_query = """
            SELECT
                T.team_id,
                T.team_name,
                COUNT(TM.player_id) AS member_count
            FROM
                team T
            LEFT JOIN
                team_membership TM ON T.team_id = TM.team_id AND TM.active = TRUE
            WHERE
                T.league_id = %s
            GROUP BY
                T.team_id, T.team_name
            ORDER BY
                T.team_name ASC;
        """
        cursor.execute(teams_query, (league_id,))
        teams_data = cursor.fetchall()
        
        response_data = {
            "league_id": league_id,
            "league_name": league['name'],
            "season_year": league['season_year'],
            "status": league['status'],
            "user_role": user_role,
            "user_team_id": user_team_id, 
            "teams": teams_data
        }

        return jsonify(response_data), 200

    except mysql.connector.Error as err:
        print(f"Database error in get_league_details: {err}")
        return jsonify({"error": "Server error while fetching league details"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/api/league/<int:league_id>/roster', methods=['GET'])
@login_required
def get_league_roster(league_id):
    """Retrieves all players with a 'Player' role in the specified league."""
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor(dictionary=True)

    try:
        # FIXES: player, role_assignment, user_account
        query = """
            SELECT DISTINCT
                P.player_id,
                P.first_name,
                P.last_name,
                P.email,
                RA.role
            FROM
                player P
            JOIN
                user_account UA ON P.email = UA.email
            JOIN
                role_assignment RA ON UA.user_id = RA.user_id
            WHERE
                RA.league_id = %s AND RA.role IN ('Player', 'Commissioner')
            ORDER BY
                P.last_name, P.first_name;
        """
        cursor.execute(query, (league_id,))
        roster = cursor.fetchall()
        
        return jsonify(roster), 200
        
    except mysql.connector.Error as err:
        print(f"Database error fetching roster: {err}")
        return jsonify({"error": f"Error executing query: {err}"}), 500
    finally:
        cursor.close()
        conn.close()

# ==================== TEAM ENDPOINTS ====================

# C:\projects\league-manager-api\app.py (Add these functions)

@app.route('/api/league/<int:league_id>/teams', methods=['GET'])
@login_required
def get_teams(league_id):
    """Retrieves all teams in a league, including their size, members, and the current user's team ID."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "User not logged in"}), 401

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor(dictionary=True)

    try:
        # 1. Fetch all teams and their members in one go
        teams_members_query = """
            SELECT 
                T.team_id, 
                T.team_name AS name, 
                P.player_id, 
                P.first_name, 
                P.last_name
            FROM 
                team T
            LEFT JOIN 
                team_membership TM ON T.team_id = TM.team_id
            LEFT JOIN
                player P ON TM.player_id = P.player_id
            WHERE 
                T.league_id = %s
            ORDER BY
                T.team_name, P.last_name;
        """
        cursor.execute(teams_members_query, (league_id,))
        results = cursor.fetchall()

        # 2. Reorganize flat list into nested structure in Python
        teams_map = {}
        for row in results:
            team_id = row['team_id']
            if team_id not in teams_map:
                teams_map[team_id] = {
                    'team_id': team_id,
                    'name': row['name'],
                    'current_size': 0,
                    'members': []
                }
            
            # If player_id exists (i.e., not a team with 0 members)
            if row['player_id']:
                teams_map[team_id]['members'].append({
                    'player_id': row['player_id'],
                    'name': f"{row['first_name']} {row['last_name']}"
                })
                teams_map[team_id]['current_size'] += 1

        teams_list = list(teams_map.values())
        
        # 3. Check if the current user is already on a team in this league
        user_team_query = """
            SELECT 
                TM.team_id 
            FROM 
                team_membership TM
            JOIN 
                team T ON TM.team_id = T.team_id
            JOIN
                player P ON TM.player_id = P.player_id
            JOIN
                user_account UA ON P.email = UA.email
            WHERE 
                T.league_id = %s AND UA.user_id = %s;
        """
        cursor.execute(user_team_query, (league_id, user_id))
        user_team = cursor.fetchone()
        
        user_team_id = user_team['team_id'] if user_team else None
        
        return jsonify({
            "teams": teams_list,
            "user_team_id": user_team_id
        }), 200

    except mysql.connector.Error as err:
        print(f"Database error fetching teams: {err}")
        return jsonify({"error": f"Error executing query: {err}"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/league/<int:league_id>/teams', methods=['POST'])
@login_required
def create_team(league_id):
    """Allows a player to create a new team and automatically joins them."""
    data = request.get_json()
    team_name = data.get('name')
    user_id = session.get('user_id')

    if not all([team_name, user_id]):
        return jsonify({"error": "Missing team name or user session data"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor()
    
    try:
        # 1. Get the player_id from user_id (linking UA <-> P via email)
        player_q = "SELECT player_id FROM player WHERE email = (SELECT email FROM user_account WHERE user_id = %s)"
        cursor.execute(player_q, (user_id,))
        player_result = cursor.fetchone()
        if not player_result:
            return jsonify({"error": "User does not have a linked Player record."}), 400
        player_id = player_result[0]

        # 2. Check if the player is already on a team in this league (using team_membership)
        check_query = """
            SELECT 
                TM.team_id 
            FROM 
                team_membership TM
            JOIN 
                team T ON TM.team_id = T.team_id
            WHERE 
                T.league_id = %s AND TM.player_id = %s;
        """
        cursor.execute(check_query, (league_id, player_id))
        if cursor.fetchone():
            return jsonify({"error": "You are already on a team in this league."}), 409

        # 3. Create the team
        create_team_query = "INSERT INTO team (team_name, league_id) VALUES (%s, %s)"
        cursor.execute(create_team_query, (team_name, league_id))
        team_id = cursor.lastrowid
        
        # 4. Add player to the team (using team_membership)
        join_query = "INSERT INTO team_membership (team_id, player_id) VALUES (%s, %s)"
        cursor.execute(join_query, (team_id, player_id))

        conn.commit()
        
        return jsonify({
            "message": f"Team '{team_name}' created successfully. You have been added to the team.",
            "team_id": team_id
        }), 201

    except mysql.connector.Error as err:
        conn.rollback()
        if err.errno == 1062:
            return jsonify({"error": f"Team name '{team_name}' already exists in this league."}), 409
        print(f"Database error creating team: {err}")
        return jsonify({"error": f"Error executing query: {err}"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/team/<int:team_id>/join', methods=['POST'])
@login_required
def join_team(team_id):
    """Allows a player to join an existing team, enforcing max size of 2."""
    MAX_TEAM_SIZE = 2
    user_id = session.get('user_id')

    if not user_id:
        return jsonify({"error": "User not logged in"}), 401

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor()
    
    try:
        # 1. Get player_id and team info
        player_q = "SELECT player_id FROM player WHERE email = (SELECT email FROM user_account WHERE user_id = %s)"
        cursor.execute(player_q, (user_id,))
        player_result = cursor.fetchone()
        if not player_result:
            return jsonify({"error": "User does not have a linked Player record."}), 400
        player_id = player_result[0]
        
        cursor.execute("SELECT league_id, team_name FROM team WHERE team_id = %s", (team_id,))
        team_result = cursor.fetchone()
        if not team_result:
            return jsonify({"error": "Team not found."}), 404
        league_id = team_result[0]
        team_name = team_result[1]

        # 2. Check if the player is already on a team in this league (using team_membership)
        check_query = """
            SELECT 
                TM.team_id 
            FROM 
                team_membership TM
            JOIN 
                team T ON TM.team_id = T.team_id
            WHERE 
                T.league_id = %s AND TM.player_id = %s;
        """
        cursor.execute(check_query, (league_id, player_id))
        if cursor.fetchone():
            return jsonify({"error": "You are already on a team in this league. Leave your current team first."}), 409

        # 3. Check current team size (using team_membership)
        cursor.execute("SELECT COUNT(*) FROM team_membership WHERE team_id = %s", (team_id,))
        current_size = cursor.fetchone()[0]

        if current_size >= MAX_TEAM_SIZE:
            return jsonify({"error": f"Team is full. Max size is {MAX_TEAM_SIZE}."}), 409

        # 4. Add player to the team (using team_membership)
        join_query = "INSERT INTO team_membership (team_id, player_id) VALUES (%s, %s)"
        cursor.execute(join_query, (team_id, player_id))

        conn.commit()
        
        return jsonify({"message": f"Successfully joined team '{team_name}'."}), 200

    except mysql.connector.Error as err:
        conn.rollback()
        print(f"Database error joining team: {err}")
        return jsonify({"error": f"Error executing query: {err}"}), 500
    finally:
        cursor.close()
        conn.close()



# ==================== PLAYER ENDPOINTS ====================

@app.route('/api/players', methods=['GET'])
@login_required
def get_players():
    """Get players with search and sort."""
    search = request.args.get('q', '')
    sort_by = request.args.get('sort', 'name')
    order = request.args.get('order', 'asc')
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        # FIX: player
        query = "SELECT player_id, first_name, last_name, email FROM player WHERE 1=1"
        params = []
        
        if search:
            query += " AND (first_name LIKE %s OR last_name LIKE %s OR email LIKE %s)"
            search_param = f"%{search}%"
            params.extend([search_param, search_param, search_param])
        
        if sort_by == 'email':
            query += f" ORDER BY email {order.upper()}"
        else: 
            query += f" ORDER BY last_name {order.upper()}, first_name {order.upper()}"
        
        cursor.execute(query, tuple(params))
        players = cursor.fetchall()
        
        return jsonify(players), 200
        
    except mysql.connector.Error as err:
        print(f"Error fetching players: {err}")
        return jsonify({"error": "Failed to fetch players"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/players', methods=['POST'])
@login_required
def create_player():
    """Create a new player."""
    data = request.get_json()
    first_name = data.get('first_name')
    last_name = data.get('last_name')
    email = data.get('email')
    
    if not all([first_name, last_name]):
        return jsonify({"error": "First name and last name are required"}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor()
    
    try:
        # FIX: player
        query = "INSERT INTO player (first_name, last_name, email) VALUES (%s, %s, %s)"
        cursor.execute(query, (first_name, last_name, email))
        player_id = cursor.lastrowid
        
        conn.commit()
        return jsonify({
            "message": "Player created successfully",
            "player_id": player_id
        }), 201
        
    except mysql.connector.Error as err:
        if err.errno == 1062:
            return jsonify({"error": "A player with this email already exists"}), 409
        print(f"Error creating player: {err}")
        return jsonify({"error": "Failed to create player"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/players/<int:player_id>', methods=['PUT'])
@login_required
def update_player(player_id):
    """Update a player's information."""
    data = request.get_json()
    first_name = data.get('first_name')
    last_name = data.get('last_name')
    email = data.get('email')
    
    if not all([first_name, last_name]):
        return jsonify({"error": "First name and last name are required"}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor()
    
    try:
        # FIX: player
        query = """
            UPDATE player
            SET first_name = %s, last_name = %s, email = %s
            WHERE player_id = %s
        """
        cursor.execute(query, (first_name, last_name, email, player_id))
        
        if cursor.rowcount == 0:
            return jsonify({"error": "Player not found"}), 404
        
        conn.commit()
        return jsonify({"message": "Player updated successfully"}), 200
        
    except mysql.connector.Error as err:
        if err.errno == 1062:
            return jsonify({"error": "A player with this email already exists"}), 409
        print(f"Error updating player: {err}")
        return jsonify({"error": "Failed to update player"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/players/<int:player_id>', methods=['DELETE'])
@login_required
def delete_player(player_id):
    """Delete a player."""
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor()
    
    try:
        # FIX: team_membership
        check_query = """
            SELECT COUNT(*) FROM team_membership
            WHERE player_id = %s AND active = TRUE
        """
        cursor.execute(check_query, (player_id,))
        active_count = cursor.fetchone()[0]
        
        if active_count > 0:
            return jsonify({"error": "Cannot delete player with active team memberships"}), 409
        
        # FIX: player
        cursor.execute("DELETE FROM player WHERE player_id = %s", (player_id,))
        
        if cursor.rowcount == 0:
            return jsonify({"error": "Player not found"}), 404
        
        conn.commit()
        return jsonify({"message": "Player deleted successfully"}), 200
        
    except mysql.connector.Error as err:
        print(f"Error deleting player: {err}")
        return jsonify({"error": "Failed to delete player"}), 500
    finally:
        cursor.close()
        conn.close()

# ==================== GAME ENDPOINTS (Requires further fixing of queries) ====================
# NOTE: The below endpoints are included for completeness but will need auditing 
# for consistency with the new lowercase snake_case table names (Game->game, Team->team, etc.)

@app.route('/api/games', methods=['GET'])
@login_required
def get_games():
    """Get games with filters and sorting."""
    league_id = request.args.get('league_id')
    status = request.args.get('status') 
    team_id = request.args.get('team_id')
    sort_by = request.args.get('sort', 'date')
    order = request.args.get('order', 'desc')
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        # FIXES: Game->game, Team->team
        query = """
            SELECT
                g.game_id,
                g.league_id,
                g.status,
                g.scheduled_at,
                g.playoff_flag,
                g.round_best_of,
                ht.team_name as home_team_name,
                at.team_name as away_team_name,
                g.home_team,
                g.away_team
            FROM game g
            JOIN team ht ON g.home_team = ht.team_id
            JOIN team at ON g.away_team = at.team_id
            WHERE 1=1
        """
        
        params = []
        
        if league_id:
            query += " AND g.league_id = %s"
            params.append(league_id)
            
        if status:
            query += " AND g.status = %s"
            params.append(status)
            
        if team_id:
            query += " AND (g.home_team = %s OR g.away_team = %s)"
            params.append(team_id)
            params.append(team_id)
        
        if sort_by == 'status':
            query += f" ORDER BY g.status {order.upper()}, g.scheduled_at DESC"
        else: 
            query += f" ORDER BY g.scheduled_at {order.upper()}"
        
        cursor.execute(query, tuple(params))
        games = cursor.fetchall()
        
        return jsonify(games), 200
        
    except mysql.connector.Error as err:
        print(f"Error fetching games: {err}")
        return jsonify({"error": "Failed to fetch games"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/games', methods=['POST'])
@role_required('Commissioner')
def create_game():
    """Schedules a new game, requires Commissioner role."""
    data = request.get_json()
    league_id = data.get('league_id')
    home_team = data.get('home_team')
    away_team = data.get('away_team')
    scheduled_at = data.get('scheduled_at')
    round_best_of = data.get('round_best_of', 1)

    if not all([league_id, home_team, away_team]):
        return jsonify({"error": "Missing league_id, home_team, or away_team"}), 400
    if home_team == away_team:
        return jsonify({"error": "Home and away teams must be different"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    try:
        # FIX: Team->team
        team_check_query = """
            SELECT COUNT(team_id) FROM team
            WHERE team_id IN (%s, %s) AND league_id = %s
        """
        cursor.execute(team_check_query, (home_team, away_team, league_id))
        if cursor.fetchone()[0] != 2:
            return jsonify({"error": "Teams must belong to the specified league."}), 403

        # FIXES: Game->game, GameRound->game_round
        game_query = """
            INSERT INTO game (league_id, status, scheduled_at, home_team, away_team, round_best_of)
            VALUES (%s, 'Scheduled', %s, %s, %s, %s)
        """
        cursor.execute(game_query, (league_id, scheduled_at, home_team, away_team, round_best_of))
        game_id = cursor.lastrowid

        round_query = "INSERT INTO game_round (game_id, round_number, status) VALUES (%s, 1, 'Pending')"
        cursor.execute(round_query, (game_id,))

        conn.commit()
        return jsonify({"message": "Game scheduled successfully", "game_id": game_id}), 201

    except mysql.connector.Error as err:
        print(f"Game creation error: {err}")
        return jsonify({"error": "Game creation failed"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/games/<int:game_id>', methods=['DELETE'])
@role_required('Commissioner')
def delete_game(game_id):
    """Delete a game (Commissioner only)."""
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor()
    try:
        # FIX: Game->game
        cursor.execute("DELETE FROM game WHERE game_id = %s", (game_id,))
        
        if cursor.rowcount == 0:
            return jsonify({"error": "Game not found"}), 404
        
        conn.commit()
        return jsonify({"message": "Game deleted successfully"}), 200
        
    except mysql.connector.Error as err:
        print(f"Error deleting game: {err}")
        return jsonify({"error": "Failed to delete game"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/games/<int:game_id>/events', methods=['POST'])
@role_required('Commissioner')
def log_round_event(game_id):
    """Logs a single event to a game round."""
    data = request.get_json()
    
    league_id = data.get('league_id')
    round_number = data.get('round_number')
    sequence_number = data.get('sequence_number')
    player_id = data.get('player_id')
    event_type = data.get('event_type')
    player_lp_delta = data.get('player_lp_delta', 0)

    if not all([league_id, round_number, sequence_number, player_id, event_type]):
        return jsonify({"error": "Missing required event data"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    try:
        # FIX: TeamMembership->team_membership
        team_q = "SELECT team_id FROM team_membership WHERE player_id = %s AND active = TRUE"
        cursor.execute(team_q, (player_id,))
        player_team_id = cursor.fetchone()
        if not player_team_id:
            return jsonify({"error": f"Player ID {player_id} not found or not active."}), 404
        player_team_id = player_team_id[0]

        # FIX: RoundEvent->round_event, GameRound->game_round
        event_query = """
            INSERT INTO round_event (
                game_id, round_number, sequence_number, player_team_id, player_id,
                opponent_team_id, opponent_player_id, event_type, player_lp_delta, opponent_lp_delta
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(event_query, (
            game_id, round_number, sequence_number, player_team_id, player_id,
            data.get('opponent_team_id'), data.get('opponent_player_id'),
            event_type, player_lp_delta, data.get('opponent_lp_delta', 0)
        ))
        conn.commit()

        return jsonify({"message": "Event logged successfully"}), 201

    except mysql.connector.Error as err:
        print(f"Event logging error: {err}")
        if err.errno == 1062:
            return jsonify({"error": "Sequence number already exists for this round."}), 409
        return jsonify({"error": "Event logging failed"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/games/<int:game_id>/finalize', methods=['POST'])
@role_required('Commissioner')
def finalize_game(game_id):
    """Executes the stored procedure to finalize a game and tally stats."""
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
    try:
        cursor.callproc('sp_TallyAndFinalizeGame', (game_id,))
        
        for result in cursor.stored_results():
            final_message = result.fetchone()[0]

        conn.commit()
        return jsonify({"message": final_message}), 200

    except mysql.connector.Error as err:
        print(f"Game finalization error: {err}")
        return jsonify({"error": str(err)}), 500
    finally:
        cursor.close()
        conn.close()

# ==================== STATS ENDPOINTS (Fixing all table names) ====================

@app.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    """Get player statistics with filtering and sorting."""
    league_id = request.args.get('league_id')
    player_id = request.args.get('player_id')
    category = request.args.get('category')
    sort_by = request.args.get('sort', 'value') 
    order = request.args.get('order', 'desc')
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        # FIXES: PlayerSeasonMetric, Player, SeasonStatCategory -> player_season_metric, player, season_stat_category
        query = """
            SELECT
                psm.league_id,
                psm.season_year,
                psm.player_id,
                CONCAT(p.first_name, ' ', p.last_name) as player_name,
                psm.category_code,
                ssc.display_name as category_name,
                psm.metric_value
            FROM player_season_metric psm
            JOIN player p ON psm.player_id = p.player_id
            JOIN season_stat_category ssc ON psm.category_code = ssc.category_code
            WHERE 1=1
        """
        
        params = []
        
        if league_id:
            query += " AND psm.league_id = %s"
            params.append(league_id)
            
        if player_id:
            query += " AND psm.player_id = %s"
            params.append(player_id)
            
        if category:
            query += " AND psm.category_code = %s"
            params.append(category)
        
        if sort_by == 'player':
            query += f" ORDER BY player_name {order.upper()}, psm.metric_value DESC"
        elif sort_by == 'category':
            query += f" ORDER BY psm.category_code {order.upper()}, psm.metric_value DESC"
        else: 
            query += f" ORDER BY psm.metric_value {order.upper()}, player_name ASC"
        
        cursor.execute(query, tuple(params))
        stats = cursor.fetchall()
        
        return jsonify(stats), 200
        
    except mysql.connector.Error as err:
        print(f"Error fetching stats: {err}")
        return jsonify({"error": "Failed to fetch statistics"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/league/<int:league_id>/awards', methods=['POST'])
@role_required('Commissioner')
def calculate_awards(league_id):
    """Calculates season awards based on PlayerSeasonMetric data."""
    data = request.get_json()
    season_year = data.get('season_year')
    
    if not season_year:
        return jsonify({"error": "Missing season_year"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    cursor = conn.cursor()
    try:
        # FIXES: SeasonAward, PlayerSeasonMetric -> season_award, player_season_metric
        delete_awards_query = "DELETE FROM season_award WHERE league_id = %s AND season_year = %s"
        cursor.execute(delete_awards_query, (league_id, season_year))
        
        award_query = """
            INSERT INTO season_award (league_id, season_year, category_code, winner_player_id, metric_value)
            SELECT
                league_id,
                season_year,
                category_code,
                player_id,
                metric_value
            FROM (
                SELECT
                    league_id,
                    season_year,
                    category_code,
                    player_id,
                    metric_value,
                    ROW_NUMBER() OVER (PARTITION BY category_code ORDER BY metric_value DESC) as rn
                FROM player_season_metric
                WHERE league_id = %s AND season_year = %s
            ) ranked
            WHERE rn = 1
        """
        cursor.execute(award_query, (league_id, season_year))
        
        conn.commit()
        return jsonify({
            "message": f"Awards for League {league_id}, Season {season_year} calculated and updated.",
            "awards_created": cursor.rowcount
        }), 200

    except mysql.connector.Error as err:
        print(f"Award calculation error: {err}")
        return jsonify({"error": "Award calculation failed"}), 500
    finally:
        cursor.close()
        conn.close()

# ==================== UTILITY ENDPOINTS ====================

@app.route('/api/status', methods=['GET'])
def status():
    conn = get_db_connection()
    if conn and conn.is_connected():
        conn.close()
        return jsonify({"status": "API running", "db_status": "Connected"}), 200
    else:
        return jsonify({"status": "API running", "db_status": "Failed to connect"}), 500

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

if __name__ == '__main__':
    # Ensure all tables are created *before* running the app for the first time in a clean environment
    # Note: If you run this file directly, it's safe to assume the tables exist after running create_db.py
    app.run(debug=True)