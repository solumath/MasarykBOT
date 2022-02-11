-- Table: server.guilds

-- DROP TABLE server.guilds;

CREATE TABLE server.guilds
(
    id bigint NOT NULL,
    name character varying(30) COLLATE pg_catalog."default" NOT NULL,
    icon_url text COLLATE pg_catalog."default",
    created_at timestamp without time zone NOT NULL DEFAULT now(),
    edited_at timestamp without time zone,
    deleted_at timestamp without time zone,
    CONSTRAINT guilds_pkey PRIMARY KEY (id)
)

TABLESPACE pg_default;

ALTER TABLE server.guilds
    OWNER to masaryk;
