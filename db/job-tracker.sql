CREATE TABLE IF NOT EXISTS ResumeDetails(
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    AnonymousSessionId Text NULL,
    Name Text NOT NULL,
    Email Text NOT NULL,
    Skills Text CHECK(json_valid(Skills)) NOT NULL,
    Experience Text NOT NULL,
    Phone Text NULL,
    Urls Text NULL CHECK(Urls IS NULL OR json_valid(Urls)),          -- JSON array of profile URLs (LinkedIn, portfolio, GitHub)
    Location Text NULL,
    CurrentPosition Text NULL,
    Summary Text NULL,
    Projects Text NULL CHECK(Projects IS NULL OR json_valid(Projects)), -- JSON array of {name, description, technologies_used}
    Education Text NULL,
    OriginalFileName Text NOT NULL,
    OriginalFilePath Text NOT NULL,

    UNIQUE(Email, OriginalFilePath)
);

CREATE TABLE IF NOT EXISTS JobDetails(
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    AnonymousSessionId Text NULL,
    CompanyName Text NOT NULL,
    Position Text NOT NULL,
    YearsOfExperienceRequired Integer NULL,
    JobLocation Text NULL,
    JobDescription Text  NOT NULL,
    JobUrl Text NOT NULL,    
    JobPostingDate Date  NULL,
    IsOpen INTEGER NOT NULL DEFAULT 0 CHECK (IsOpen IN (0, 1)),  -- 0 if position closed, 1 if open
    PointsOfContact Text NULL,
    PointsOfContactEmail Text NULL,
    Notes Text NULL,

    UNIQUE(JobUrl)
);

CREATE TABLE IF NOT EXISTS JobApplications(
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    AnonymousSessionId Text NULL,
    ResumeId Integer NOT NULL,
    JobId Integer NOT NULL,
    MatchScorePercent Integer NULL CHECK(MatchScorePercent >= 0 AND MatchScorePercent <= 100),
    MatchReasoning Text NULL,
    MatchedSkills Text NULL CHECK(MatchedSkills IS NULL OR json_valid(MatchedSkills)),
    MissingSkills Text NULL CHECK(MissingSkills IS NULL OR json_valid(MissingSkills)),
    Status Text NULL, -- "Applied", "Interviewing", "Offered", "Rejected","Closed","Not Applied"
    TailoredResumeId Integer NULL, -- FK to the generated tailored ResumeDetails row for this (resume x job)
    CreatedAt  Text DEFAULT(datetime('now')),

    FOREIGN KEY (ResumeId) REFERENCES ResumeDetails(Id),
    FOREIGN KEY (JobId) REFERENCES JobDetails(Id),
    FOREIGN KEY (TailoredResumeId) REFERENCES ResumeDetails(Id),

    UNIQUE(ResumeId, JobId)
);

CREATE TABLE IF NOT EXISTS PreparationMaterials(
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    AnonymousSessionId Text NULL,
    JobApplicationId   Integer NOT NULL,
    MaterialType Text NOT NULL,
    MaterialContent Text NOT NULL,
    InterviewQuestions Text CHECK(json_valid(InterviewQuestions)) NULL,
    STARResponses Text CHECK(json_valid(STARResponses)) NULL,
    STARQuestions Text CHECK(json_valid(STARQuestions)) NULL,
    FOREIGN KEY (JobApplicationId) REFERENCES JobApplications(Id)
);

CREATE TABLE IF NOT EXISTS AnonymousSessions(
    Id Text PRIMARY KEY,
    CreatedAt Text DEFAULT(datetime('now')),
    LastSeenAt Text DEFAULT(datetime('now'))
);

CREATE TABLE IF NOT EXISTS UsageEvents(
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    AnonymousSessionId Text NOT NULL,
    EventType Text NOT NULL,
    IpHash Text NULL,
    EstimatedCostUsd REAL NOT NULL DEFAULT 0,
    Metadata Text NULL CHECK(Metadata IS NULL OR json_valid(Metadata)),
    CreatedAt Text DEFAULT(datetime('now'))
);

CREATE INDEX IF NOT EXISTS IX_ResumeDetails_AnonymousSessionId
ON ResumeDetails(AnonymousSessionId);

CREATE INDEX IF NOT EXISTS IX_JobDetails_AnonymousSessionId
ON JobDetails(AnonymousSessionId);

CREATE INDEX IF NOT EXISTS IX_JobApplications_AnonymousSessionId
ON JobApplications(AnonymousSessionId);

CREATE INDEX IF NOT EXISTS IX_PreparationMaterials_AnonymousSessionId
ON PreparationMaterials(AnonymousSessionId);

CREATE INDEX IF NOT EXISTS IX_UsageEvents_Session_Event_Created
ON UsageEvents(AnonymousSessionId, EventType, CreatedAt);

CREATE INDEX IF NOT EXISTS IX_UsageEvents_Ip_Created
ON UsageEvents(IpHash, CreatedAt);

