import os
import sqlite3

print ("Dossier de travail actuel :", os.getcwd())
print ("\nFichiers présents dans ce dossier :")
for f in os.listdir():
    print("-", f)
print("\nChemin absolu utilisé pour la base : ")
print(os.path.abspath("gestion_absences.db"))

if os.path.exists("gestion_absences.db") :
    taille = os.path.getsize("gestion_absences.db")
    print(f"\nTaille du fichier gestion_absences.db : {taille} octets")
else :
    print("\nLe fichier gestion_absences.db n'éxiste pas")