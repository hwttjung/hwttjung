import os
import json
import urllib.request
import urllib.parse
from common.logger_setup import get_domain_logger

logger = get_domain_logger("boomsbeat")

def generate_puzzle_data(theme="General Knowledge"):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not found.")
        return []
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    prompt = f"""
Generate 8 words and clues for a crossword puzzle about "{theme}".
The words should be strictly English alphabet letters, uppercase, 3 to 10 letters long, without spaces or punctuation.
Output ONLY a valid JSON object in this format:
{{
  "words": [
    {{"word": "SPACE", "clue": "The final frontier"}},
    {{"word": "GALAXY", "clue": "A huge collection of gas, dust, and billions of stars"}}
  ]
}}
"""
    payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8")
            data = json.loads(body)
            # parse response
            try:
                text = data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError):
                text = ""
                
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end != -1:
            data = json.loads(text[start:end])
            return data.get("words", [])
        return []
    except Exception as e:
        logger.error(f"Error generating crossword words via REST: {e}")
        return []

def build_grid(words):
    if not words: return [], {}
    words = sorted(words, key=lambda w: len(w["word"]), reverse=True)
    grid = {}
    placements = []
    
    def can_place(w, x, y, dr):
        for i, char in enumerate(w):
            cx = x + (i if dr == 0 else 0)
            cy = y + (i if dr == 1 else 0)
            if (cx, cy) in grid and grid[(cx, cy)] != char:
                return False
            if (cx, cy) not in grid:
                neighbors = [(cx, cy-1), (cx, cy+1)] if dr == 0 else [(cx-1, cy), (cx+1, cy)]
                for nx, ny in neighbors:
                    if (nx, ny) in grid: return False
                
                if i == 0:
                    if dr == 0 and (cx-1, cy) in grid: return False
                    if dr == 1 and (cx, cy-1) in grid: return False
                if i == len(w) - 1:
                    if dr == 0 and (cx+1, cy) in grid: return False
                    if dr == 1 and (cx, cy+1) in grid: return False
        return True

    def place_word(w_dict, x, y, dr):
        w = w_dict["word"]
        for i, char in enumerate(w):
            cx = x + (i if dr == 0 else 0)
            cy = y + (i if dr == 1 else 0)
            grid[(cx, cy)] = char
        placements.append({
            "word": w,
            "clue": w_dict["clue"],
            "x": x,
            "y": y,
            "dir": "across" if dr == 0 else "down"
        })

    place_word(words[0], 0, 0, 0)
    
    for w_dict in words[1:]:
        w = w_dict["word"].upper()
        w_dict["word"] = w
        best_placement = None
        for i, char in enumerate(w):
            for (gx, gy), gchar in grid.items():
                if char == gchar:
                    for dr in [0, 1]:
                        sx = gx - (i if dr == 0 else 0)
                        sy = gy - (i if dr == 1 else 0)
                        if can_place(w, sx, sy, dr):
                            best_placement = (sx, sy, dr)
                            break
            if best_placement:
                break
        if best_placement:
            place_word(w_dict, best_placement[0], best_placement[1], best_placement[2])

    if len(placements) < 3:
        return [], {}
        
    placements.sort(key=lambda p: (p["y"], p["x"]))
    num = 1
    numbered_cells = {}
    for p in placements:
        cell = (p["x"], p["y"])
        if cell not in numbered_cells:
            numbered_cells[cell] = num
            num += 1
        p["num"] = numbered_cells[cell]

    return placements, grid

def render_crossword_html(placements, grid, theme):
    if not placements: return ""
    
    min_x = min(x for (x, y) in grid.keys())
    max_x = max(x for (x, y) in grid.keys())
    min_y = min(y for (x, y) in grid.keys())
    max_y = max(y for (x, y) in grid.keys())
    
    cell_size = "30px"
    html = f"<h3>Boomsbeat Mini Crossword: {theme}</h3>"
    html += "<p>Print this page or solve it mentally! The answers are at the bottom.</p>"
    html += "<div><table border=1 cellpadding=2 cellspacing=0>"
    
    num_map = { (p["x"], p["y"]): p["num"] for p in placements }
    
    for y in range(min_y, max_y + 1):
        html += "<tr>"
        for x in range(min_x, max_x + 1):
            if (x, y) in grid:
                number = num_map.get((x, y), "")
                if number:
                    num_html = f"<b>{number}</b><br/>&emsp;&emsp;"
                else:
                    num_html = f"&emsp;&emsp;<br/>&emsp;&emsp;"
                html += f"<td align=left valign=top bgcolor=#ffffff>{num_html}</td>"
            else:
                html += f"<td bgcolor=#000000>&emsp;&emsp;<br/>&emsp;&emsp;</td>"
        html += "</tr>"
    html += "</table></div>"
    
    html += "<h4>Across</h4><ul>"
    for p in placements:
        if p["dir"] == "across":
            html += f"<li><b>{p['num']}</b>. {p['clue']}</li>"
    html += "</ul>"
    
    html += "<h4>Down</h4><ul>"
    for p in placements:
        if p["dir"] == "down":
            html += f"<li><b>{p['num']}</b>. {p['clue']}</li>"
    html += "</ul>"
    
    html += "<br/><br/><br/><br/><br/><br/><h4>Answers (Spoiler)</h4><br/><br/><br/><br/><br/><ul>"
    for p in placements:
        d = "A" if p["dir"] == "across" else "D"
        html += f"<li>{p['num']}{d}: {p['word']}</li>"
    html += "</ul>"
    
    return html

def create_crossword_article(theme):
    logger.info(f"Generating crossword puzzle for theme: {theme}")
    words = generate_puzzle_data(theme)
    placements, grid = build_grid(words)
    if not placements:
        return None
        
    html_content = render_crossword_html(placements, grid, theme)
    
    return {
        "title": f"Play: {theme} Mini Crossword Puzzle",
        "content": html_content,
        "summary": f"Challenge yourself with our daily mini crossword puzzle! Today's theme is {theme}. Test your knowledge and have fun.",
        "selected_category": "Misc"
    }

if __name__ == "__main__":
    import sys
    import os
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    from common.env_loader import EnvLoader
    EnvLoader.load_env()
    res = create_crossword_article("Technology and Gadgets")
    if res:
        print(res["title"])
        print(res["summary"])
        print("---")
        print(res["content"])
    else:
        print("Failed to generate.")
