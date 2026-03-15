#!/usr/bin/env python3
"""
Script de scraping quotidien.
Lance le scraping de tous les comptes et sauvegarde un snapshot.
A lancer via cron/launchd une fois par jour.

Usage: python3 daily_scrape.py
"""
import sys
import os

# Ensure we're in the right directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from database import init_db, get_all_accounts, save_daily_snapshot
from tiktok_scraper import scrape_all_accounts_for_user
from datetime import datetime

def main():
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Scraping quotidien...")
    init_db()

    # Get all users that have accounts
    from database import _fetchall, get_connection
    conn = get_connection()
    users = _fetchall(conn, "SELECT DISTINCT user_id FROM accounts WHERE user_id IS NOT NULL")
    conn.close()

    if not users:
        print("Aucun utilisateur avec des comptes.")
        return

    for user_row in users:
        user_id = user_row['user_id']
        accounts = get_all_accounts(user_id=user_id)
        print(f"\nUser {user_id}: {len(accounts)} comptes")

        def on_start(username):
            print(f"  Scraping @{username}...")

        def on_done(username, success, video_count):
            status = "OK" if success else "ERREUR"
            print(f"  @{username}: {status} ({video_count} videos)")

        scrape_all_accounts_for_user(user_id, on_start=on_start, on_done=on_done)

    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Scraping termine!")


if __name__ == "__main__":
    main()
