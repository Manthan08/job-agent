from typing import List
from pydantic import BaseModel, Field, EmailStr, ValidationError

class ExperienceItem(BaseModel):
    company: str
    role_title: str
    start_date: str = Field(description="The start date of the experience")
    end_date: str | None = Field(default=None, description="The end date of the experience")
    work_description: str = Field(description="A brief description of the work performed during the experience")

class ProjectItem(BaseModel):
    name: str = Field(description="The name of the project")
    description: str  = Field(description="A brief description of the project")
    technologies_used: List[str] = Field(description="List of technologies used in the project")

class ResumeModel(BaseModel):
    name: str = Field(description="The candidate's full name")
    current_position: str = Field(description="The candidate's current job position or title E.g - Software Engineer")
    phone: str | None = Field(default=None, description="The candidate's phone number E.g - +91-9612345678 or 09612345678")
    email: EmailStr = Field(description="The candidate's email address E.g - example@example.com")
    urls: List[str] = Field(description="The candidate's personal profile/contact URLs from the resume "
                            "HEADER/contact area ONLY — e.g. LinkedIn, personal portfolio/website, GitHub profile. "
                            "Do NOT include URLs that belong to individual projects, employers, articles, or products.")
    location: str | None = Field(default=None, description="The candidate's location")
    summary: str | None = Field(default=None, description="A brief summary about the candidate")
    skills: List[str] = Field(description="List of skills (e.g., ['C#', 'LangChain', 'Azure'])")
    experience: List[ExperienceItem] | None = Field(default=None, description="List of work experiences, each represented by an ExperienceItem")
    education: str | None = Field(default=None, description="Optional field for education details")
    projects: List[ProjectItem] | None = Field(default=None, description="Optional field for projects, each project can be a ProjectItem")