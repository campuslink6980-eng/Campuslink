"""
Dynamic course recommendation with static curated platforms and auto YouTube search.
No external or paid APIs. Business logic only.
"""
from typing import Dict, List
from urllib.parse import quote_plus

# ---------------------------------------------------------------------------
# A) Static mapping: curated courses (Coursera & Udemy)
#    Each skill maps to list of { platform, title, link }
#    Keys are normalized (lowercase) for case-insensitive lookup.
# ---------------------------------------------------------------------------
CURATED_COURSES: Dict[str, List[Dict[str, str]]] = {
    "react": [
        {"platform": "Coursera", "title": "Front-End Development with React", "link": "https://www.coursera.org/learn/front-end-react"},
        {"platform": "Udemy", "title": "React - The Complete Guide", "link": "https://www.udemy.com/topic/react/"},
    ],
    "python": [
        {"platform": "Coursera", "title": "Python for Everybody", "link": "https://www.coursera.org/specializations/python"},
        {"platform": "Udemy", "title": "Complete Python Bootcamp", "link": "https://www.udemy.com/topic/python/"},
    ],
    "aws": [
        {"platform": "Coursera", "title": "AWS Cloud Technical Essentials", "link": "https://www.coursera.org/learn/aws-cloud-technical-essentials"},
        {"platform": "Udemy", "title": "AWS Certified Solutions Architect", "link": "https://www.udemy.com/topic/aws/"},
    ],
    "docker": [
        {"platform": "Coursera", "title": "Containers, Docker and Kubernetes", "link": "https://www.coursera.org/learn/containers-docker-kubernetes"},
        {"platform": "Udemy", "title": "Docker Mastery", "link": "https://www.udemy.com/topic/docker/"},
    ],
    # Extended curated entries (optional; same structure)
    "javascript": [
        {"platform": "Coursera", "title": "JavaScript Basics", "link": "https://www.coursera.org/learn/javascript-basics"},
        {"platform": "Udemy", "title": "The Complete JavaScript Course", "link": "https://www.udemy.com/topic/javascript/"},
    ],
    "java": [
        {"platform": "Coursera", "title": "Java Programming", "link": "https://www.coursera.org/learn/java-programming"},
        {"platform": "Udemy", "title": "Java Masterclass", "link": "https://www.udemy.com/topic/java/"},
    ],
    "sql": [
        {"platform": "Coursera", "title": "SQL for Data Science", "link": "https://www.coursera.org/learn/sql-for-data-science"},
        {"platform": "Udemy", "title": "The Complete SQL Bootcamp", "link": "https://www.udemy.com/topic/sql/"},
    ],
    "machine learning": [
        {"platform": "Coursera", "title": "Machine Learning Specialization", "link": "https://www.coursera.org/specializations/machine-learning-introduction"},
        {"platform": "Udemy", "title": "Machine Learning A-Z", "link": "https://www.udemy.com/topic/machine-learning/"},
    ],
}


# ---------------------------------------------------------------------------
# B) Dynamic YouTube search generator (NO API)
# ---------------------------------------------------------------------------
def generate_youtube_search(skill: str) -> str:
    """
    Build a URL-safe YouTube search URL for the given skill.
    No API calls; only string encoding.
    Format: https://www.youtube.com/results?search_query=<skill>+course
    """
    if not skill or not isinstance(skill, str):
        skill = ""
    # Strip and normalize: replace internal spaces with + for query
    clean = " ".join(skill.strip().split())
    if not clean:
        return "https://www.youtube.com/results?search_query=course"
    # URL-encode the query (e.g. "React Hooks" -> "React+Hooks+course")
    query = quote_plus(clean + " course")
    return f"https://www.youtube.com/results?search_query={query}"


def _normalize_skill(s: str) -> str:
    """Normalize for dedup and lookup: strip, lowercase."""
    return s.strip().lower() if s else ""


def _canonical_skill(s: str) -> str:
    """Return display form: strip, single spaces, original casing where possible."""
    return " ".join((s or "").strip().split())


# ---------------------------------------------------------------------------
# C) Main recommendation function
# ---------------------------------------------------------------------------
def recommend_courses(user_skills: List[str]) -> List[Dict[str, str]]:
    """
    Recommend courses for a list of skills.
    For each skill: adds curated courses (Coursera/Udemy if available), then one YouTube search link.
    Case-insensitive matching, stripped spaces, no duplicate skills.
    Returns a flat list of { "skill", "platform", "title", "link" }.
    """
    seen_keys: set = set()
    result: List[Dict[str, str]] = []

    for raw in user_skills:
        if not isinstance(raw, str):
            continue
        key = _normalize_skill(raw)
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        display_skill = _canonical_skill(raw) or raw

        # 1) Curated courses (if available)
        curated = CURATED_COURSES.get(key)
        if curated:
            for c in curated:
                result.append({
                    "skill": display_skill,
                    "platform": c.get("platform") or "Unknown",
                    "title": c.get("title") or f"{display_skill} course",
                    "link": c.get("link") or "#",
                })

        # 2) Always add one YouTube dynamic search link per skill
        result.append({
            "skill": display_skill,
            "platform": "YouTube",
            "title": f"{display_skill} course on YouTube",
            "link": generate_youtube_search(display_skill),
        })

    return result


def recommend_courses_grouped_by_skill(user_skills: List[str]) -> Dict[str, List[Dict[str, str]]]:
    """
    Same as recommend_courses but returns dict grouped by skill for backward compatibility.
    Keys: original skill strings. Values: list of { platform, link, name } (name = title).
    """
    flat = recommend_courses(user_skills)
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for item in flat:
        skill = item.get("skill") or "Other"
        if skill not in grouped:
            grouped[skill] = []
        grouped[skill].append({
            "platform": item.get("platform") or "Unknown",
            "link": item.get("link") or "#",
            "name": item.get("title") or f"{skill} course",
        })
    return grouped


# ---------------------------------------------------------------------------
# Example usage
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    skills = ["React", "Python"]
    print("recommend_courses(skills):")
    for r in recommend_courses(skills):
        print(f"  {r}")
    print("\nrecommend_courses_grouped_by_skill(skills):")
    print(recommend_courses_grouped_by_skill(skills))
