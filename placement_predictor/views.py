import logging

from django.shortcuts import render

from .forms import StudentPlacementForm
from .services import PlacementModelError, predict_placement

logger = logging.getLogger(__name__)


def _preparation_feedback(data):
    checks = [
        ("CGPA", data["CGPA"], 7.0, "Aim for a CGPA of 7 or higher."),
        ("Aptitude test", data["Aptitude_Test_Score"], 60, "Practice aptitude tests and review weak question types."),
        ("Communication", data["Communication_Skills"], 60, "Build communication confidence with mock discussions and presentations."),
        ("Mock interviews", data["Mock_Interview_Score"], 60, "Practice technical and behavioral mock interviews."),
        ("Projects", data["Projects_Count"], 2, "Build and document at least two substantial projects."),
        ("Internships", data["Internships"], 1, "Look for internship or practical industry experience."),
        ("DSA practice", data["DSA_Problems_Solved"], 100, "Set a regular data structures and algorithms practice goal."),
        ("Resume", data["Resume_Score"], 60, "Review your resume for clear impact, skills, and project outcomes."),
        ("Certifications", data["Certifications"], 1, "Complete a relevant certification and apply the skills in a project."),
        ("LeetCode rating", data["LeetCode_Rating"], 1200, "Practice timed coding problems and review each solution."),
        ("GitHub contributions", data["GitHub_Contributions"], 100, "Publish consistent, well-documented work to GitHub."),
        ("Hackathons", data["Hackathons_Participated"], 1, "Join a hackathon to practice building and presenting under time limits."),
        ("AI/ML skills", data["AI_ML_Skill_Level"], 5, "Build a small applied AI/ML project and explain its evaluation."),
        ("System design", data["System_Design_Knowledge"], 5, "Study core system design concepts and practice explaining tradeoffs."),
    ]
    strengths = [name for name, value, threshold, _ in checks if value >= threshold]
    improvement_areas = [
        {"area": name, "current": value, "target": threshold, "tip": tip}
        for name, value, threshold, tip in checks if value < threshold
    ]
    improvement_areas.sort(key=lambda area: area["current"] / area["target"])
    return strengths, improvement_areas


def predict(request):
    result = None
    form = StudentPlacementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            prediction_data = form.as_prediction_data()
            result = predict_placement(
                prediction_data,
                student_id=request.session.get("lpu_user_id"),
            )
            result["target_is_single_class"] = result.get("class_count", 2) < 2
            result["strengths"], result["improvement_areas"] = _preparation_feedback(prediction_data)
        except PlacementModelError as error:
            form.add_error(None, str(error))
        except Exception as error:
            logger.exception("Placement prediction failed")
            form.add_error(
                None,
                "The prediction could not be completed. Check the server log for the underlying error; "
                "if MongoDB is unavailable, start it and verify MONGO_URI.",
            )
    if result:
        result["placed_probability_pct"] = round(result["placed_probability"] * 100, 1)
    return render(request, "placement_predictor/predict.html", {"form": form, "result": result})
