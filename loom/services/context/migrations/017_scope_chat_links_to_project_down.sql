ALTER TABLE chat_links DROP CONSTRAINT IF EXISTS uq_chat_links_project_url;
ALTER TABLE chat_links ADD CONSTRAINT chat_links_chat_url_key UNIQUE (chat_url);
