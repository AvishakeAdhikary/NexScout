import type { CareerPath } from "./api/client";

export const CAREER_PATH_LABELS: Record<CareerPath, string> = {
  undecided: "Path not chosen",
  phd: "PhD & research",
  employment: "Employment",
  both: "PhD and employment",
};

export const CAREER_PATH_HELP: Record<CareerPath, string> = {
  undecided: "Choose later. Nothing is lost when you change your mind.",
  phd: "Find programs, funded positions, and supervisors; prepare academic documents.",
  employment: "Find jobs that fit your experience; prepare resumes and cover letters.",
  both: "Explore both paths side by side.",
};
