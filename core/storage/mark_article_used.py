#!/usr/bin/env python3
import os
import shutil
import argparse
import json

UNUSED_DIR = "data/local_articles/unused"
USED_DIR = "data/local_articles/used"

def ensure_dirs():
    os.makedirs(UNUSED_DIR, exist_ok=True)
    os.makedirs(USED_DIR, exist_ok=True)

def list_unused(domain=None):
    ensure_dirs()
    files = [f for f in os.listdir(UNUSED_DIR) if f.endswith(".json")]
    if domain:
        files = [f for f in files if f.startswith(f"{domain}_")]
    
    if not files:
        print(f"No unused articles found" + (f" for domain '{domain}'." if domain else "."))
        return
    
    # Sort files by filename
    files.sort()
    
    print(f"\n==================================================")
    print(f" Unused Articles List" + (f" (Domain: {domain})" if domain else ""))
    print(f"==================================================")
    for idx, f in enumerate(files, 1):
        filepath = os.path.join(UNUSED_DIR, f)
        try:
            with open(filepath, "r", encoding="utf-8") as file:
                data = json.load(file)
            title = data.get("generated", {}).get("title", "No Title")
            date_str = data.get("timestamp", "No Date")
            print(f"{idx:2d}. [{f}] {title} ({date_str})")
        except Exception:
            print(f"{idx:2d}. [{f}] (Error reading file)")
    print(f"==================================================\nTotal: {len(files)} unused articles\n")

def mark_used(filename):
    ensure_dirs()
    src = os.path.join(UNUSED_DIR, filename)
    dst = os.path.join(USED_DIR, filename)
    
    if not os.path.exists(src):
        # Try checking if they provided path
        basename = os.path.basename(filename)
        src = os.path.join(UNUSED_DIR, basename)
        dst = os.path.join(USED_DIR, basename)
        
    if not os.path.exists(src):
        print(f"[Error] File '{filename}' not found in unused folder: {UNUSED_DIR}")
        return False
        
    try:
        shutil.move(src, dst)
        print(f"[Success] Article '{os.path.basename(src)}' has been marked as USED (moved to {USED_DIR}/)")
        return True
    except Exception as e:
        print(f"[Error] Failed to move file: {e}")
        return False

def mark_all_used(domain):
    ensure_dirs()
    files = [f for f in os.listdir(UNUSED_DIR) if f.endswith(".json") and f.startswith(f"{domain}_")]
    if not files:
        print(f"No unused articles found to mark as used for domain '{domain}'.")
        return
        
    success_count = 0
    for f in files:
        if mark_used(f):
            success_count += 1
            
    print(f"\nCompleted! Marked {success_count} / {len(files)} articles as USED for domain '{domain}'.")

def main():
    parser = argparse.ArgumentParser(description="Manage unused/used states of local generated articles.")
    parser.add_argument("-l", "--list", action="store_true", help="List all unused articles.")
    parser.add_argument("-f", "--file", type=str, help="Mark a specific article file as USED (move to used/ folder).")
    parser.add_argument("-d", "--domain", type=str, help="Filter by domain key or pair with --all to batch update.")
    parser.add_argument("-a", "--all", action="store_true", help="Mark all filtered articles as USED.")
    
    args = parser.parse_args()
    
    if args.list:
        list_unused(args.domain)
    elif args.file:
        mark_used(args.file)
    elif args.domain and args.all:
        # Direct batch update
        mark_all_used(args.domain)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
