import os
from flask import Flask, jsonify, send_file, make_response
from flask_cors import CORS
from dotenv import load_dotenv
import mysql.connector
from flask import request, session, Blueprint, g
from flask_bcrypt import Bcrypt
import csv
import json
from io import StringIO, BytesIO
from datetime import datetime
from functools import wraps

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

def get_db_connection():
    try:
        # Check if we should use secure database user
        use_secure = os.getenv("USE_SECURE_DB", "false").lower() == "true"
       
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
           
            # Try to get league_id from query params if not in body
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
        password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

        # Insert into UserAccount
        user_query = "INSERT INTO UserAccount (name, email, password_hash) VALUES (%s, %s, %s)"
        cursor.execute(user_query, (name, email, password_hash))
        user_id = cursor.lastrowid

        # Insert or Update Player
        player_query = """
            INSERT INTO Player (first_name, last_name, email, user_id)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE user_id = VALUES(user_id)
        """
        first_name, *last_name_parts = name.split(' ')
        last_name = ' '.join(last_name_parts) if last_name_parts else ''

        cursor.execute(player_query, (first_name, last_name, email, user_id))

        conn.commit()
        return jsonify({"message": "Registration successful. You can now log in."}), 201

    except mysql.connector.Error as err:
        if err.errno == 1062:
            return jsonify({"error": "This email is already registered."}), 409
        print(f"Database error during registration: {err}")
        return jsonify({"error": "Registration failed due to server error"}), 500
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
        query = "SELECT user_id, password_hash, name FROM UserAccount WHERE email = %s"
        cursor.execute(query, (email,))
        user = cursor.fetchone()

        if user and bcrypt.check_password_hash(user['password_hash'], password):
            session['logged_in'] = True
            session['user_id'] = user['user_id']
            session['email'] = email
            session['name'] = user['name']

            return jsonify({"message": "Login successful", "name": user['name']}), 200
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
                League L
            JOIN
                RoleAssignment RA ON L.league_id = RA.league_id
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
    season_year = data.get('season_year')
   
    user_id = session.get('user_id')

    if not all([league_name, season_year, user_id]):
        return jsonify({"error": "Missing league name, season year, or user session data"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
   
    try:
        league_query = "INSERT INTO League (name, season_year, status) VALUES (%s, %s, 'Draft')"
        cursor.execute(league_query, (league_name, season_year))
        league_id = cursor.lastrowid
       
        role_query = "INSERT INTO RoleAssignment (user_id, league_id, role) VALUES (%s, %s, %s)"
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
        cursor.execute("DELETE FROM League WHERE league_id = %s", (league_id,))
       
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
    sort_by = request.args.get('sort', 'year_desc')  # year_desc, year_asc, name_asc, name_desc

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor(dictionary=True)
   
    query = "SELECT league_id, name, season_year, status FROM League WHERE 1=1 "
    params = []
   
    if search_term:
        query += "AND name LIKE %s "
        params.append(f"%{search_term}%")
   
    if season_year and season_year.isdigit():
        query += "AND season_year = %s "
        params.append(season_year)

    # Add sorting
    if sort_by == 'year_asc':
        query += "ORDER BY season_year ASC, name ASC"
    elif sort_by == 'name_asc':
        query += "ORDER BY name ASC, season_year DESC"
    elif sort_by == 'name_desc':
        query += "ORDER BY name DESC, season_year DESC"
    else:  # default: year_desc
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
        check_query = "SELECT role FROM RoleAssignment WHERE user_id = %s AND league_id = %s"
        cursor.execute(check_query, (user_id, league_id))
        if cursor.fetchone():
            return jsonify({"error": "You are already a member of this league."}), 409

        role_query = "INSERT INTO RoleAssignment (user_id, league_id, role) VALUES (%s, %s, %s)"
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
        role_query = "SELECT role FROM RoleAssignment WHERE user_id = %s AND league_id = %s"
        cursor.execute(role_query, (current_user_id, league_id))
        user_info = cursor.fetchone()

        if not user_info:
            return jsonify({"error": "User is not a member of this league"}), 403

        user_role = user_info['role']
       
        user_team_id = None
        team_check_query = """
            SELECT T.team_id
            FROM Team T
            JOIN TeamMembership TM ON T.team_id = TM.team_id
            JOIN Player P ON TM.player_id = P.player_id
            WHERE P.user_id = %s AND T.league_id = %s AND TM.active = TRUE
        """
        cursor.execute(team_check_query, (current_user_id, league_id))
        team_row = cursor.fetchone()
        if team_row:
            user_team_id = team_row['team_id']
       
        league_query = "SELECT name, season_year, status FROM League WHERE league_id = %s"
        cursor.execute(league_query, (league_id,))
        league = cursor.fetchone()
        if not league:
            return jsonify({"error": "League not found"}), 404

        teams_query = """
            SELECT
                T.team_id,
                T.team_name,
                COUNT(TM.player_id) AS member_count
            FROM
                Team T
            LEFT JOIN
                TeamMembership TM ON T.team_id = TM.team_id AND TM.active = TRUE
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

# ==================== TEAM ENDPOINTS ====================

@app.route('/api/team', methods=['POST'])
@login_required
def create_team():
    data = request.get_json()
    league_id = data.get('league_id')
    team_name = data.get('team_name')
    user_id = session.get('user_id')

    if not all([league_id, team_name, user_id]):
        return jsonify({"error": "Missing data or user session"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
   
    try:
        check_member_q = "SELECT COUNT(*) FROM RoleAssignment WHERE user_id = %s AND league_id = %s"
        cursor.execute(check_member_q, (user_id, league_id))
        if cursor.fetchone()[0] == 0:
             return jsonify({"error": "You must be a member of the league to create a team."}), 403
       
        player_q = "SELECT player_id FROM Player WHERE user_id = %s"
        cursor.execute(player_q, (user_id,))
        player_row = cursor.fetchone()
       
        if not player_row:
            return jsonify({"error": "Player profile not found for this user."}), 500

        player_id = player_row[0]

        check_active_q = """
            SELECT COUNT(TM.player_id)
            FROM TeamMembership TM
            JOIN Team T ON TM.team_id = T.team_id
            WHERE TM.player_id = %s AND T.league_id = %s AND TM.active = TRUE
        """
        cursor.execute(check_active_q, (player_id, league_id))
        if cursor.fetchone()[0] > 0:
             return jsonify({"error": "You are already an active member of a team in this league."}), 409
       
        team_query = "INSERT INTO Team (league_id, team_name) VALUES (%s, %s)"
        cursor.execute(team_query, (league_id, team_name))
        team_id = cursor.lastrowid
       
        membership_query = """
            INSERT INTO TeamMembership (team_id, player_id, active, joined_at)
            VALUES (%s, %s, TRUE, NOW())
        """
        cursor.execute(membership_query, (team_id, player_id))

        conn.commit()
       
        return jsonify({
            "message": "Team created successfully. You are now the first member!",
            "team_id": team_id
        }), 201

    except mysql.connector.Error as err:
        conn.rollback()
        if err.errno == 1062:
            return jsonify({"error": f"Team name '{team_name}' already exists in this league."}), 409
        print(f"Database error during team creation: {err}")
        return jsonify({"error": "Team creation failed due to server error"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/teams', methods=['GET'])
@login_required
def get_teams():
    """Get teams with search, filter, and sort capabilities."""
    league_id = request.args.get('league_id')
    search = request.args.get('search', '')
    sort_by = request.args.get('sort', 'name')  # name, members
    order = request.args.get('order', 'asc')  # asc, desc
   
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
   
    cursor = conn.cursor(dictionary=True)
   
    try:
        query = """
            SELECT
                T.team_id,
                T.team_name,
                T.league_id,
                L.name as league_name,
                COUNT(TM.player_id) AS member_count
            FROM
                Team T
            JOIN
                League L ON T.league_id = L.league_id
            LEFT JOIN
                TeamMembership TM ON T.team_id = TM.team_id AND TM.active = TRUE
            WHERE 1=1
        """
       
        params = []
       
        if league_id:
            query += " AND T.league_id = %s"
            params.append(league_id)
           
        if search:
            query += " AND T.team_name LIKE %s"
            params.append(f"%{search}%")
       
        query += " GROUP BY T.team_id, T.team_name, T.league_id, L.name"
       
        # Add sorting
        if sort_by == 'members':
            query += f" ORDER BY member_count {order.upper()}, T.team_name ASC"
        else:  # default to name
            query += f" ORDER BY T.team_name {order.upper()}"
       
        cursor.execute(query, tuple(params))
        teams = cursor.fetchall()
       
        return jsonify(teams), 200
       
    except mysql.connector.Error as err:
        print(f"Error fetching teams: {err}")
        return jsonify({"error": "Failed to fetch teams"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/team/<int:team_id>', methods=['DELETE'])
@role_required('Commissioner')
def delete_team(team_id):
    """Delete a team (Commissioner only)."""
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
   
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM Team WHERE team_id = %s", (team_id,))
       
        if cursor.rowcount == 0:
            return jsonify({"error": "Team not found"}), 404
       
        conn.commit()
        return jsonify({"message": "Team deleted successfully"}), 200
       
    except mysql.connector.Error as err:
        print(f"Error deleting team: {err}")
        return jsonify({"error": "Failed to delete team"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/team/join', methods=['POST'])
@login_required
def join_team():
    data = request.get_json()
    league_id = data.get('league_id')
    team_id = data.get('team_id')
    user_id = session.get('user_id')

    if not all([league_id, team_id, user_id]):
        return jsonify({"error": "Missing data (league_id or team_id) or user session"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()
   
    try:
        player_q = "SELECT player_id FROM Player WHERE user_id = %s"
        cursor.execute(player_q, (user_id,))
        player_row = cursor.fetchone()
       
        if not player_row:
            return jsonify({"error": "Player profile not found for this user."}), 500

        player_id = player_row[0]

        check_active_q = """
            SELECT COUNT(TM.player_id)
            FROM TeamMembership TM
            JOIN Team T ON TM.team_id = T.team_id
            WHERE TM.player_id = %s AND T.league_id = %s AND TM.active = TRUE
        """
        cursor.execute(check_active_q, (player_id, league_id))
        if cursor.fetchone()[0] > 0:
             return jsonify({"error": "You are already an active member of a team in this league."}), 409

        roster_size_q = "SELECT COUNT(player_id) FROM TeamMembership WHERE team_id = %s AND active = TRUE"
        cursor.execute(roster_size_q, (team_id,))
        current_size = cursor.fetchone()[0]

        if current_size >= 2:
            return jsonify({"error": "This team's roster is already full (maximum 2 players)."}), 409
       
        membership_query = """
            INSERT INTO TeamMembership (team_id, player_id, active, joined_at)
            VALUES (%s, %s, TRUE, NOW())
        """
        cursor.execute(membership_query, (team_id, player_id))

        conn.commit()
       
        return jsonify({
            "message": "Successfully joined the team!",
            "team_id": team_id
        }), 200

    except mysql.connector.Error as err:
        conn.rollback()
        print(f"Database error during team join: {err}")
        return jsonify({"error": "Failed to join team due to server error"}), 500
    finally:
        cursor.close()
        conn.close()

# ==================== PLAYER ENDPOINTS ====================

@app.route('/api/players', methods=['GET'])
@login_required
def get_players():
    """Get players with search and sort."""
    search = request.args.get('q', '')
    sort_by = request.args.get('sort', 'name')  # name, email
    order = request.args.get('order', 'asc')
   
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
   
    cursor = conn.cursor(dictionary=True)
   
    try:
        query = "SELECT player_id, first_name, last_name, email FROM Player WHERE 1=1"
        params = []
       
        if search:
            query += " AND (first_name LIKE %s OR last_name LIKE %s OR email LIKE %s)"
            search_param = f"%{search}%"
            params.extend([search_param, search_param, search_param])
       
        # Add sorting
        if sort_by == 'email':
            query += f" ORDER BY email {order.upper()}"
        else:  # default to name
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
        query = "INSERT INTO Player (first_name, last_name, email) VALUES (%s, %s, %s)"
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
        query = """
            UPDATE Player
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
        # Check if player has active team memberships
        check_query = """
            SELECT COUNT(*) FROM TeamMembership
            WHERE player_id = %s AND active = TRUE
        """
        cursor.execute(check_query, (player_id,))
        active_count = cursor.fetchone()[0]
       
        if active_count > 0:
            return jsonify({"error": "Cannot delete player with active team memberships"}), 409
       
        cursor.execute("DELETE FROM Player WHERE player_id = %s", (player_id,))
       
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

# ==================== GAME ENDPOINTS ====================

@app.route('/api/games', methods=['GET'])
@login_required
def get_games():
    """Get games with filters and sorting."""
    league_id = request.args.get('league_id')
    status = request.args.get('status')  # Scheduled, In Progress, Completed
    team_id = request.args.get('team_id')
    sort_by = request.args.get('sort', 'date')  # date, status
    order = request.args.get('order', 'desc')
   
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
   
    cursor = conn.cursor(dictionary=True)
   
    try:
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
            FROM Game g
            JOIN Team ht ON g.home_team = ht.team_id
            JOIN Team at ON g.away_team = at.team_id
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
       
        # Add sorting
        if sort_by == 'status':
            query += f" ORDER BY g.status {order.upper()}, g.scheduled_at DESC"
        else:  # default to date
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
        team_check_query = """
            SELECT COUNT(team_id) FROM Team
            WHERE team_id IN (%s, %s) AND league_id = %s
        """
        cursor.execute(team_check_query, (home_team, away_team, league_id))
        if cursor.fetchone()[0] != 2:
            return jsonify({"error": "Teams must belong to the specified league."}), 403

        game_query = """
            INSERT INTO Game (league_id, status, scheduled_at, home_team, away_team, round_best_of)
            VALUES (%s, 'Scheduled', %s, %s, %s, %s)
        """
        cursor.execute(game_query, (league_id, scheduled_at, home_team, away_team, round_best_of))
        game_id = cursor.lastrowid

        round_query = "INSERT INTO GameRound (game_id, round_number, status) VALUES (%s, 1, 'Pending')"
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
        cursor.execute("DELETE FROM Game WHERE game_id = %s", (game_id,))
       
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
        team_q = "SELECT team_id FROM TeamMembership WHERE player_id = %s AND active = TRUE"
        cursor.execute(team_q, (player_id,))
        player_team_id = cursor.fetchone()
        if not player_team_id:
            return jsonify({"error": f"Player ID {player_id} not found or not active."}), 404
        player_team_id = player_team_id[0]

        event_query = """
            INSERT INTO RoundEvent (
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

# ==================== STATS ENDPOINTS ====================

@app.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    """Get player statistics with filtering and sorting."""
    league_id = request.args.get('league_id')
    player_id = request.args.get('player_id')
    category = request.args.get('category')
    sort_by = request.args.get('sort', 'value')  # value, player, category
    order = request.args.get('order', 'desc')
   
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
   
    cursor = conn.cursor(dictionary=True)
   
    try:
        query = """
            SELECT
                psm.league_id,
                psm.season_year,
                psm.player_id,
                CONCAT(p.first_name, ' ', p.last_name) as player_name,
                psm.category_code,
                ssc.display_name as category_name,
                psm.metric_value
            FROM PlayerSeasonMetric psm
            JOIN Player p ON psm.player_id = p.player_id
            JOIN SeasonStatCategory ssc ON psm.category_code = ssc.category_code
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
       
        # Add sorting
        if sort_by == 'player':
            query += f" ORDER BY player_name {order.upper()}, psm.metric_value DESC"
        elif sort_by == 'category':
            query += f" ORDER BY psm.category_code {order.upper()}, psm.metric_value DESC"
        else:  # default to value
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
        # Clear old awards
        delete_awards_query = "DELETE FROM SeasonAward WHERE league_id = %s AND season_year = %s"
        cursor.execute(delete_awards_query, (league_id, season_year))
       
        # Calculate and insert new awards
        # Get top player for each category
        award_query = """
            INSERT INTO SeasonAward (league_id, season_year, category_code, winner_player_id, metric_value)
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
                FROM PlayerSeasonMetric
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

# ==================== EXPORT ENDPOINTS ====================

@app.route('/api/export/<export_type>', methods=['GET'])
@login_required
def export_data(export_type):
    """Export data in JSON, CSV, or HTML format."""
    format_type = request.args.get('format', 'json')  # json, csv, html
    league_id = request.args.get('league_id')
   
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
   
    cursor = conn.cursor(dictionary=True)
   
    try:
        # Determine what to export
        if export_type == 'teams':
            query = """
                SELECT
                    T.team_id,
                    T.team_name,
                    L.name as league_name,
                    L.season_year,
                    COUNT(TM.player_id) as member_count
                FROM Team T
                JOIN League L ON T.league_id = L.league_id
                LEFT JOIN TeamMembership TM ON T.team_id = TM.team_id AND TM.active = TRUE
                WHERE 1=1
            """
            params = []
            if league_id:
                query += " AND T.league_id = %s"
                params.append(league_id)
            query += " GROUP BY T.team_id, T.team_name, L.name, L.season_year"
           
        elif export_type == 'games':
            query = """
                SELECT
                    g.game_id,
                    l.name as league_name,
                    g.status,
                    g.scheduled_at,
                    ht.team_name as home_team,
                    at.team_name as away_team,
                    g.playoff_flag,
                    g.round_best_of
                FROM Game g
                JOIN League l ON g.league_id = l.league_id
                JOIN Team ht ON g.home_team = ht.team_id
                JOIN Team at ON g.away_team = at.team_id
                WHERE 1=1
            """
            params = []
            if league_id:
                query += " AND g.league_id = %s"
                params.append(league_id)
               
        elif export_type == 'stats':
            query = """
                SELECT
                    l.name as league_name,
                    psm.season_year,
                    CONCAT(p.first_name, ' ', p.last_name) as player_name,
                    ssc.display_name as stat_category,
                    psm.metric_value
                FROM PlayerSeasonMetric psm
                JOIN League l ON psm.league_id = l.league_id
                JOIN Player p ON psm.player_id = p.player_id
                JOIN SeasonStatCategory ssc ON psm.category_code = ssc.category_code
                WHERE 1=1
            """
            params = []
            if league_id:
                query += " AND psm.league_id = %s"
                params.append(league_id)
            query += " ORDER BY psm.metric_value DESC"
           
        else:
            return jsonify({"error": "Invalid export type. Choose: teams, games, or stats"}), 400
       
        cursor.execute(query, tuple(params))
        data = cursor.fetchall()
       
        # Format the response based on requested format
        if format_type == 'csv':
            if not data:
                return "No data available", 200, {'Content-Type': 'text/csv'}
           
            output = StringIO()
            writer = csv.DictWriter(output, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
           
            response = make_response(output.getvalue())
            response.headers["Content-Disposition"] = f"attachment; filename={export_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            response.headers["Content-Type"] = "text/csv"
            return response
           
        elif format_type == 'html':
            if not data:
                html = "<html><body><h2>No data available</h2></body></html>"
            else:
                html = f"<html><head><title>{export_type.title()} Export</title>"
                html += "<style>table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px}th{background:#f2f2f2}</style>"
                html += f"</head><body><h2>{export_type.title()} Data</h2><table>"
                html += "<tr>" + "".join(f"<th>{k}</th>" for k in data[0].keys()) + "</tr>"
                for row in data:
                    html += "<tr>" + "".join(f"<td>{v}</td>" for v in row.values()) + "</tr>"
                html += "</table></body></html>"
           
            return html, 200, {'Content-Type': 'text/html'}
           
        else:  # default to json
            return jsonify(data), 200
           
    except mysql.connector.Error as err:
        print(f"Error exporting data: {err}")
        return jsonify({"error": "Failed to export data"}), 500
    finally:
        cursor.close()
        conn.close()

# ==================== IMPORT ENDPOINTS ====================

@app.route('/api/import/players', methods=['POST'])
@role_required('Commissioner')
def import_players():
    """Import players from CSV or JSON."""
    if 'file' not in request.files:
        # Check if JSON data in body
        data = request.get_json()
        if not data:
            return jsonify({"error": "No file or JSON data provided"}), 400
        players_data = data.get('players', [])
    else:
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
       
        # Determine file type
        if file.filename.endswith('.csv'):
            # Parse CSV
            stream = StringIO(file.stream.read().decode("UTF8"), newline=None)
            csv_reader = csv.DictReader(stream)
            players_data = list(csv_reader)
        elif file.filename.endswith('.json'):
            # Parse JSON
            players_data = json.load(file)
            if isinstance(players_data, dict):
                players_data = players_data.get('players', [])
        else:
            return jsonify({"error": "Unsupported file format. Use CSV or JSON"}), 400
   
    if not players_data:
        return jsonify({"error": "No player data found"}), 400
   
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
   
    cursor = conn.cursor()
    imported_count = 0
    skipped_count = 0
   
    try:
        for player in players_data:
            first_name = player.get('first_name')
            last_name = player.get('last_name')
            email = player.get('email')
           
            if not first_name or not last_name:
                skipped_count += 1
                continue
           
            try:
                query = "INSERT INTO Player (first_name, last_name, email) VALUES (%s, %s, %s)"
                cursor.execute(query, (first_name, last_name, email))
                imported_count += 1
            except mysql.connector.Error as err:
                if err.errno == 1062:  # Duplicate
                    skipped_count += 1
                else:
                    raise err
       
        conn.commit()
        return jsonify({
            "message": "Import completed",
            "imported": imported_count,
            "skipped": skipped_count
        }), 200
       
    except Exception as err:
        conn.rollback()
        print(f"Error importing players: {err}")
        return jsonify({"error": "Failed to import players"}), 500
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
    app.run(debug=True)