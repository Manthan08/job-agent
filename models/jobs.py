from datetime import date
from pydantic import BaseModel, Field

# class ExperienceItem(BaseModel):
#     company: str
#     role_title: str
#     start_date: str = Field(description="The start date of the experience")
#     end_date: str | None = Field(default=None, description="The end date of the experience")
#     work_description: str = Field(description="A brief description of the work performed during the experience")

# class ProjectItem(BaseModel):
#     name: str = Field(description="The name of the project")
#     description: str  = Field(description="A brief description of the project")
#     technologies_used: List[str] = Field(description="List of technologies used in the project")

class JobDetailsModel(BaseModel):
    company_name: str = Field(description="The name of the company offering the job")
    position: str = Field(description="The title of the job position")
    years_of_experience_required: int | None = Field(default=None, description="The number of years of experience required for the job")
    job_location: str | None = Field(default=None, description="The location of the job, if applicable")
    job_description: str = Field(description="A brief description of the job responsibilities and requirements")
    job_url: str = Field(description="The URL to the job posting")
    job_posting_date: date | None = Field(default=None, description="The date when the job was posted")
    is_open: bool | None = Field(default=None, description="Indicates whether the job is currently open for applications")
    point_of_contact: str | None = Field(default=None, description="The point of contact for the job application, such as a name or email address or phone number")
    point_of_contact_email: str | None = Field(default=None, description="The email address of the point of contact for the job application")
    notes: str | None = Field(default=None, description="Additional notes or comments about the job")