Work Memory — Features and Design Decisions to Preserve



This document captures the features, ideas, and design principles discussed for Work Memory. These should remain part of the project's direction, even if they are not all implemented immediately.



Project organization and quick access


Pin or star important projects: Allow users to pin frequently accessed projects so they remain easily accessible, ideally near the top of the project list.
Quick project access: Make it easy to jump back into recently accessed or pinned projects without navigating through multiple screens.
Preserve project identity: Each project should retain its description, activity history, files, notes, attachments, and milestones.
Keep navigation simple: Avoid introducing too many categories, nested menus, or competing navigation systems.


2. Quick Capture and contextual notifications



Quick Capture should be accessible manually at any time, as well as through contextual notifications.



Non-intrusive notifications: Small, subtle notifications should appear when relevant activity is detected, such as a new file being created.
Quick actions from notifications: Allow users to add a note, record something, or save an important event without opening the full application.
Milestone action directly in notifications: Include the ability to star or pin an event as an important milestone directly from the notification.
Project association: Captured information should be associated with the relevant project and activity whenever possible.
Recoverable drafts: If the user starts a capture but doesn't finish it, the draft should remain recoverable.


3. Audio recording and notes



Allow users to start an audio recording directly from Quick Capture.
Support optional speech-to-text transcription.
Preserve the original audio recording independently of its transcription, if the user chooses to keep it.
Allow audio recordings to be associated with a project and a particular activity or date.
Support text notes alongside audio recordings and other attachments.
Make recordings and their transcriptions easy to find and review later.


4. Screenshots and image attachments



Allow screenshots to be captured directly through Quick Capture.
Support attaching existing images as well as newly captured screenshots.
Provide basic screenshot annotation tools:
Pen / freehand drawing
Arrows
Shapes
Text
Crop
Undo
Allow a single capture to contain multiple attachments.
Preserve the original screenshot or image alongside any annotated version.
Associate screenshots with the relevant project and activity.


5. Project history and milestones



The history of a project is one of Work Memory's most important features.



Complete chronological history: Preserve project activity over time, including file creation, changes, notes, screenshots, recordings, and other relevant events.
Milestone starring / pinning: Allow users to mark important events as milestones using a simple star or pin system.
Milestones near the top: Provide a dedicated, easily accessible milestone area near the top of the project page.
Keep the original timeline intact: Marking an event as a milestone should not remove it from its chronological position.
User-controlled importance: Users should be able to decide which events matter. AI can suggest important events, but should not independently determine the entire milestone history.
Preserve context: Keep the relationships between events, dates, notes, screenshots, recordings, and files.


6. Project summaries and history navigation



Large projects may eventually contain hundreds of files and activity records. Users need a way to understand what happened without manually reviewing everything.



Consider three levels of information:



Project summary: The overall purpose, current state, major accomplishments, and remaining work.
Recent activity summary: What happened today, during the last session, or since the previous visit.
Complete history: The original chronological record, always accessible.


Additional requirements:



Summaries should act as entry points into the original information, not replacements for it.
Whenever possible, clicking an item in a summary should take the user to the relevant note, screenshot, file, recording, or activity entry.
Summaries should be regeneratable as the project evolves.
Original notes, attachments, metadata, and activity records must remain independent of AI-generated summaries.
Make it easy to navigate project history by date, including through the calendar.


7. Project page information hierarchy



Keep project pages calm and easy to understand.



A possible vertical structure:



Project name and description
Project summary
Important milestones
Recent activity
Complete chronological history
Files and attachments
Calendar / timeline navigation


This is a suggested hierarchy, not a rigid layout. The important thing is that information should be organized naturally and not forced into a single crowded viewport.



8. Interface philosophy



These principles are important and should guide future development:



Work Memory should reduce cognitive load, not create another source of it.
The interface should feel calm, spacious, and approachable.
Prefer clear vertical organization and comfortable scrolling over squeezing everything into multiple panels.
Avoid unnecessary dashboards, duplicate search fields, excessive categories, and visual clutter.
Notifications should be subtle and useful, never demanding constant attention.
The application should be able to run in the background without requiring the user to manage it constantly.
Do not turn Work Memory into another Notion, task manager, project-management platform, or file explorer.
Do not add features simply because other productivity applications have them.
Prioritize real-world usefulness over feature count.


9. Core product philosophy



Work Memory should remember the work you do rather than asking you to manage the work you're doing.



Its purpose is to preserve the evolution and context of projects over time, so that users can return months or even years later and understand:



What the project was originally about.
What changed and why.
What was accomplished.
Which technical decisions were made.
What problems were encountered.
What the last known development state was.
Where the relevant files, notes, screenshots, and recordings can be found.


The central idea: Work Memory isn't trying to make you work better. It's trying to make sure your work doesn't disappear into the past.



10. Development priorities



These ideas do not all need to be implemented immediately.



Prioritize in this order:



Complete and stabilize existing Quick Capture functionality, especially screenshot capture.
Ensure notes, images, audio recordings, files, and activity entries are properly associated with projects.
Implement project pinning and milestone starring, including the ability to mark a milestone directly from a contextual notification.
Refine project history and milestone presentation.
Develop useful project and recent-activity summaries.
Improve calendar-based history navigation and quick access.


After the core functionality is stable, use Work Memory in real work before introducing more features. Let actual usage reveal what is missing.



Important: Do not compromise the simplicity of the application just to accommodate every idea. Preserve these requirements as a reference, but implement them progressively. 