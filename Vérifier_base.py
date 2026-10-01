import sqlite3
conn = sqlite3.connect ("gestion_absences.db")
cur = conn.cursor()

cur.execute ("SELECT name FROM sqlite_master WHERE type = 'table'")
tables = cur.fetchall()

print ("Tables présentes dans la base : ")
for t in tables :
    print ("-", t [0])
    
conn.close    