HOW TO DEPLOY

1. Open XAMPP Control Panel and start Apache and MySQL (make sure it's set to port 3306)

2. Next, open the shell in XAMPP and cd into the app directory example:
   cd /d "C:\Users\cjbeb\Downloads\die_league_app"

3. If the database has not been created, run:
   python create_db.py

4. Once it's been created, or if it already was, run the following to start the app
   python app.py

5. Then open http://127.0.0.1:5000/
