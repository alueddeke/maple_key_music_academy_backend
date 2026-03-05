-- DROP SCHEMA public;

CREATE SCHEMA public AUTHORIZATION maple_key_user;

-- DROP SEQUENCE public.account_emailaddress_id_seq;

CREATE SEQUENCE public.account_emailaddress_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.account_emailconfirmation_id_seq;

CREATE SEQUENCE public.account_emailconfirmation_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.auth_group_id_seq;

CREATE SEQUENCE public.auth_group_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.auth_group_permissions_id_seq;

CREATE SEQUENCE public.auth_group_permissions_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.auth_permission_id_seq;

CREATE SEQUENCE public.auth_permission_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.billing_approvedemail_id_seq;

CREATE SEQUENCE public.billing_approvedemail_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.billing_billablecontact_id_seq;

CREATE SEQUENCE public.billing_billablecontact_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.billing_globalratesettings_id_seq;

CREATE SEQUENCE public.billing_globalratesettings_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.billing_invitationtoken_id_seq;

CREATE SEQUENCE public.billing_invitationtoken_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.billing_invoice_id_seq;

CREATE SEQUENCE public.billing_invoice_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.billing_invoice_lessons_id_seq;

CREATE SEQUENCE public.billing_invoice_lessons_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.billing_invoicerecipientemail_id_seq;

CREATE SEQUENCE public.billing_invoicerecipientemail_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.billing_lesson_id_seq;

CREATE SEQUENCE public.billing_lesson_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.billing_systemsettings_id_seq;

CREATE SEQUENCE public.billing_systemsettings_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.billing_user_assigned_teachers_id_seq;

CREATE SEQUENCE public.billing_user_assigned_teachers_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.billing_user_groups_id_seq;

CREATE SEQUENCE public.billing_user_groups_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.billing_user_id_seq;

CREATE SEQUENCE public.billing_user_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.billing_user_user_permissions_id_seq;

CREATE SEQUENCE public.billing_user_user_permissions_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.billing_userregistrationrequest_id_seq;

CREATE SEQUENCE public.billing_userregistrationrequest_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.django_admin_log_id_seq;

CREATE SEQUENCE public.django_admin_log_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.django_content_type_id_seq;

CREATE SEQUENCE public.django_content_type_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.django_migrations_id_seq;

CREATE SEQUENCE public.django_migrations_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.django_site_id_seq;

CREATE SEQUENCE public.django_site_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.socialaccount_socialaccount_id_seq;

CREATE SEQUENCE public.socialaccount_socialaccount_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.socialaccount_socialapp_id_seq;

CREATE SEQUENCE public.socialaccount_socialapp_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.socialaccount_socialapp_sites_id_seq;

CREATE SEQUENCE public.socialaccount_socialapp_sites_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.socialaccount_socialtoken_id_seq;

CREATE SEQUENCE public.socialaccount_socialtoken_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 2147483647
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.token_blacklist_blacklistedtoken_id_seq;

CREATE SEQUENCE public.token_blacklist_blacklistedtoken_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;
-- DROP SEQUENCE public.token_blacklist_outstandingtoken_id_seq;

CREATE SEQUENCE public.token_blacklist_outstandingtoken_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;-- public.auth_group definition

-- Drop table

-- DROP TABLE public.auth_group;

CREATE TABLE public.auth_group (
	id int4 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 START 1 CACHE 1 NO CYCLE) NOT NULL,
	"name" varchar(150) NOT NULL,
	CONSTRAINT auth_group_name_key UNIQUE (name),
	CONSTRAINT auth_group_pkey PRIMARY KEY (id)
);
CREATE INDEX auth_group_name_a6ea08ec_like ON public.auth_group USING btree (name varchar_pattern_ops);


-- public.billing_user definition

-- Drop table

-- DROP TABLE public.billing_user;

CREATE TABLE public.billing_user (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	"password" varchar(128) NOT NULL,
	last_login timestamptz NULL,
	is_superuser bool NOT NULL,
	first_name varchar(150) NOT NULL,
	last_name varchar(150) NOT NULL,
	is_staff bool NOT NULL,
	is_active bool NOT NULL,
	date_joined timestamptz NOT NULL,
	user_type varchar(20) NOT NULL,
	email varchar(254) NOT NULL,
	phone_number varchar(15) NOT NULL,
	address text NOT NULL,
	is_approved bool NOT NULL,
	oauth_provider varchar(50) NOT NULL,
	oauth_id varchar(100) NOT NULL,
	bio text NOT NULL,
	instruments varchar(500) NOT NULL,
	hourly_rate numeric(6, 2) NOT NULL,
	parent_email varchar(254) NOT NULL,
	parent_phone varchar(15) NOT NULL,
	CONSTRAINT billing_user_email_key UNIQUE (email),
	CONSTRAINT billing_user_pkey PRIMARY KEY (id)
);
CREATE INDEX billing_user_email_de7438c0_like ON public.billing_user USING btree (email varchar_pattern_ops);


-- public.django_content_type definition

-- Drop table

-- DROP TABLE public.django_content_type;

CREATE TABLE public.django_content_type (
	id int4 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 START 1 CACHE 1 NO CYCLE) NOT NULL,
	app_label varchar(100) NOT NULL,
	model varchar(100) NOT NULL,
	CONSTRAINT django_content_type_app_label_model_76bd3d3b_uniq UNIQUE (app_label, model),
	CONSTRAINT django_content_type_pkey PRIMARY KEY (id)
);


-- public.django_migrations definition

-- Drop table

-- DROP TABLE public.django_migrations;

CREATE TABLE public.django_migrations (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	app varchar(255) NOT NULL,
	"name" varchar(255) NOT NULL,
	applied timestamptz NOT NULL,
	CONSTRAINT django_migrations_pkey PRIMARY KEY (id)
);


-- public.django_session definition

-- Drop table

-- DROP TABLE public.django_session;

CREATE TABLE public.django_session (
	session_key varchar(40) NOT NULL,
	session_data text NOT NULL,
	expire_date timestamptz NOT NULL,
	CONSTRAINT django_session_pkey PRIMARY KEY (session_key)
);
CREATE INDEX django_session_expire_date_a5c62663 ON public.django_session USING btree (expire_date);
CREATE INDEX django_session_session_key_c0390e0f_like ON public.django_session USING btree (session_key varchar_pattern_ops);


-- public.django_site definition

-- Drop table

-- DROP TABLE public.django_site;

CREATE TABLE public.django_site (
	id int4 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 START 1 CACHE 1 NO CYCLE) NOT NULL,
	"domain" varchar(100) NOT NULL,
	"name" varchar(50) NOT NULL,
	CONSTRAINT django_site_domain_a2e37b91_uniq UNIQUE (domain),
	CONSTRAINT django_site_pkey PRIMARY KEY (id)
);
CREATE INDEX django_site_domain_a2e37b91_like ON public.django_site USING btree (domain varchar_pattern_ops);


-- public.socialaccount_socialapp definition

-- Drop table

-- DROP TABLE public.socialaccount_socialapp;

CREATE TABLE public.socialaccount_socialapp (
	id int4 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 START 1 CACHE 1 NO CYCLE) NOT NULL,
	provider varchar(30) NOT NULL,
	"name" varchar(40) NOT NULL,
	client_id varchar(191) NOT NULL,
	secret varchar(191) NOT NULL,
	"key" varchar(191) NOT NULL,
	provider_id varchar(200) NOT NULL,
	settings jsonb NOT NULL,
	CONSTRAINT socialaccount_socialapp_pkey PRIMARY KEY (id)
);


-- public.account_emailaddress definition

-- Drop table

-- DROP TABLE public.account_emailaddress;

CREATE TABLE public.account_emailaddress (
	id int4 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 START 1 CACHE 1 NO CYCLE) NOT NULL,
	email varchar(254) NOT NULL,
	verified bool NOT NULL,
	"primary" bool NOT NULL,
	user_id int8 NOT NULL,
	CONSTRAINT account_emailaddress_pkey PRIMARY KEY (id),
	CONSTRAINT account_emailaddress_user_id_email_987c8728_uniq UNIQUE (user_id, email),
	CONSTRAINT account_emailaddress_user_id_2c513194_fk_billing_user_id FOREIGN KEY (user_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX account_emailaddress_email_03be32b2 ON public.account_emailaddress USING btree (email);
CREATE INDEX account_emailaddress_email_03be32b2_like ON public.account_emailaddress USING btree (email varchar_pattern_ops);
CREATE INDEX account_emailaddress_user_id_2c513194 ON public.account_emailaddress USING btree (user_id);
CREATE UNIQUE INDEX unique_primary_email ON public.account_emailaddress USING btree (user_id, "primary") WHERE "primary";
CREATE UNIQUE INDEX unique_verified_email ON public.account_emailaddress USING btree (email) WHERE verified;


-- public.account_emailconfirmation definition

-- Drop table

-- DROP TABLE public.account_emailconfirmation;

CREATE TABLE public.account_emailconfirmation (
	id int4 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 START 1 CACHE 1 NO CYCLE) NOT NULL,
	created timestamptz NOT NULL,
	sent timestamptz NULL,
	"key" varchar(64) NOT NULL,
	email_address_id int4 NOT NULL,
	CONSTRAINT account_emailconfirmation_key_key UNIQUE (key),
	CONSTRAINT account_emailconfirmation_pkey PRIMARY KEY (id),
	CONSTRAINT account_emailconfirm_email_address_id_5b7f8c58_fk_account_e FOREIGN KEY (email_address_id) REFERENCES public.account_emailaddress(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX account_emailconfirmation_email_address_id_5b7f8c58 ON public.account_emailconfirmation USING btree (email_address_id);
CREATE INDEX account_emailconfirmation_key_f43612bd_like ON public.account_emailconfirmation USING btree (key varchar_pattern_ops);


-- public.auth_permission definition

-- Drop table

-- DROP TABLE public.auth_permission;

CREATE TABLE public.auth_permission (
	id int4 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 START 1 CACHE 1 NO CYCLE) NOT NULL,
	"name" varchar(255) NOT NULL,
	content_type_id int4 NOT NULL,
	codename varchar(100) NOT NULL,
	CONSTRAINT auth_permission_content_type_id_codename_01ab375a_uniq UNIQUE (content_type_id, codename),
	CONSTRAINT auth_permission_pkey PRIMARY KEY (id),
	CONSTRAINT auth_permission_content_type_id_2f476e4b_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX auth_permission_content_type_id_2f476e4b ON public.auth_permission USING btree (content_type_id);


-- public.billing_approvedemail definition

-- Drop table

-- DROP TABLE public.billing_approvedemail;

CREATE TABLE public.billing_approvedemail (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	email varchar(254) NOT NULL,
	user_type varchar(20) NOT NULL,
	approved_at timestamptz NOT NULL,
	notes text NOT NULL,
	approved_by_id int8 NOT NULL,
	CONSTRAINT billing_approvedemail_email_key UNIQUE (email),
	CONSTRAINT billing_approvedemail_pkey PRIMARY KEY (id),
	CONSTRAINT billing_approvedemai_approved_by_id_00a0e134_fk_billing_u FOREIGN KEY (approved_by_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX billing_approvedemail_approved_by_id_00a0e134 ON public.billing_approvedemail USING btree (approved_by_id);
CREATE INDEX billing_approvedemail_email_2756dcb1_like ON public.billing_approvedemail USING btree (email varchar_pattern_ops);


-- public.billing_billablecontact definition

-- Drop table

-- DROP TABLE public.billing_billablecontact;

CREATE TABLE public.billing_billablecontact (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	contact_type varchar(20) NOT NULL,
	first_name varchar(150) NOT NULL,
	last_name varchar(150) NOT NULL,
	email varchar(254) NOT NULL,
	phone varchar(15) NOT NULL,
	street_address varchar(255) NOT NULL,
	city varchar(100) NOT NULL,
	province varchar(2) NOT NULL,
	postal_code varchar(10) NOT NULL,
	is_primary bool NOT NULL,
	created_at timestamptz NOT NULL,
	updated_at timestamptz NOT NULL,
	student_id int8 NOT NULL,
	CONSTRAINT billing_billablecontact_pkey PRIMARY KEY (id),
	CONSTRAINT billing_billablecontact_student_id_4bff1ff9_fk_billing_user_id FOREIGN KEY (student_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT billing_billablecontact_student_id_fk_billing_user FOREIGN KEY (student_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX billing_billablecontact_student_id_4bff1ff9 ON public.billing_billablecontact USING btree (student_id);


-- public.billing_globalratesettings definition

-- Drop table

-- DROP TABLE public.billing_globalratesettings;

CREATE TABLE public.billing_globalratesettings (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	online_teacher_rate numeric(6, 2) NOT NULL,
	online_student_rate numeric(6, 2) NOT NULL,
	inperson_student_rate numeric(6, 2) NOT NULL,
	updated_at timestamptz NOT NULL,
	updated_by_id int8 NULL,
	CONSTRAINT billing_globalratesettings_pkey PRIMARY KEY (id),
	CONSTRAINT billing_globalratese_updated_by_id_80fc31f0_fk_billing_u FOREIGN KEY (updated_by_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX billing_globalratesettings_updated_by_id_80fc31f0 ON public.billing_globalratesettings USING btree (updated_by_id);


-- public.billing_invitationtoken definition

-- Drop table

-- DROP TABLE public.billing_invitationtoken;

CREATE TABLE public.billing_invitationtoken (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	email varchar(254) NOT NULL,
	"token" varchar(64) NOT NULL,
	user_type varchar(20) NOT NULL,
	created_at timestamptz NOT NULL,
	expires_at timestamptz NOT NULL,
	used_at timestamptz NULL,
	is_used bool NOT NULL,
	approved_email_id int8 NOT NULL,
	CONSTRAINT billing_invitationtoken_pkey PRIMARY KEY (id),
	CONSTRAINT billing_invitationtoken_token_key UNIQUE (token),
	CONSTRAINT billing_invitationto_approved_email_id_b918d6a0_fk_billing_a FOREIGN KEY (approved_email_id) REFERENCES public.billing_approvedemail(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX billing_invitationtoken_approved_email_id_b918d6a0 ON public.billing_invitationtoken USING btree (approved_email_id);
CREATE INDEX billing_invitationtoken_token_5474286c_like ON public.billing_invitationtoken USING btree (token varchar_pattern_ops);


-- public.billing_invoice definition

-- Drop table

-- DROP TABLE public.billing_invoice;

CREATE TABLE public.billing_invoice (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	invoice_type varchar(20) NOT NULL,
	payment_balance numeric(10, 2) NOT NULL,
	status varchar(20) NOT NULL,
	due_date timestamptz NULL,
	created_at timestamptz NOT NULL,
	approved_at timestamptz NULL,
	approved_by_id int8 NULL,
	created_by_id int8 NULL,
	student_id int8 NULL,
	teacher_id int8 NULL,
	last_edited_at timestamptz NULL,
	last_edited_by_id int8 NULL,
	notes text NOT NULL,
	invoice_number varchar(50) NULL,
	total_amount numeric(10, 2) NOT NULL,
	rejected_at timestamptz NULL,
	rejected_by_id int8 NULL,
	rejection_reason text NOT NULL,
	CONSTRAINT billing_invoice_invoice_number_key UNIQUE (invoice_number),
	CONSTRAINT billing_invoice_pkey PRIMARY KEY (id),
	CONSTRAINT billing_invoice_approved_by_id_a090b2d6_fk_billing_user_id FOREIGN KEY (approved_by_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT billing_invoice_created_by_id_c711181e_fk_billing_user_id FOREIGN KEY (created_by_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT billing_invoice_last_edited_by_id_9e5d3291_fk_billing_user_id FOREIGN KEY (last_edited_by_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT billing_invoice_rejected_by_id_d49b61e1_fk_billing_user_id FOREIGN KEY (rejected_by_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT billing_invoice_student_id_42dbb82c_fk_billing_user_id FOREIGN KEY (student_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT billing_invoice_teacher_id_84955673_fk_billing_user_id FOREIGN KEY (teacher_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX billing_invoice_approved_by_id_a090b2d6 ON public.billing_invoice USING btree (approved_by_id);
CREATE INDEX billing_invoice_created_by_id_c711181e ON public.billing_invoice USING btree (created_by_id);
CREATE INDEX billing_invoice_invoice_number_c444ad03_like ON public.billing_invoice USING btree (invoice_number varchar_pattern_ops);
CREATE INDEX billing_invoice_last_edited_by_id_9e5d3291 ON public.billing_invoice USING btree (last_edited_by_id);
CREATE INDEX billing_invoice_rejected_by_id_d49b61e1 ON public.billing_invoice USING btree (rejected_by_id);
CREATE INDEX billing_invoice_student_id_42dbb82c ON public.billing_invoice USING btree (student_id);
CREATE INDEX billing_invoice_teacher_id_84955673 ON public.billing_invoice USING btree (teacher_id);


-- public.billing_invoicerecipientemail definition

-- Drop table

-- DROP TABLE public.billing_invoicerecipientemail;

CREATE TABLE public.billing_invoicerecipientemail (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	email varchar(254) NOT NULL,
	created_at timestamptz NOT NULL,
	created_by_id int8 NULL,
	CONSTRAINT billing_invoicerecipientemail_email_key UNIQUE (email),
	CONSTRAINT billing_invoicerecipientemail_pkey PRIMARY KEY (id),
	CONSTRAINT billing_invoicerecip_created_by_id_c6af01a7_fk_billing_u FOREIGN KEY (created_by_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX billing_invoicerecipientemail_created_by_id_c6af01a7 ON public.billing_invoicerecipientemail USING btree (created_by_id);
CREATE INDEX billing_invoicerecipientemail_email_f4ee68d8_like ON public.billing_invoicerecipientemail USING btree (email varchar_pattern_ops);


-- public.billing_lesson definition

-- Drop table

-- DROP TABLE public.billing_lesson;

CREATE TABLE public.billing_lesson (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	rate numeric(6, 2) NOT NULL,
	scheduled_date timestamptz NULL,
	completed_date timestamptz NULL,
	duration numeric(6, 2) NOT NULL,
	status varchar(20) NOT NULL,
	teacher_notes text NOT NULL,
	student_notes text NOT NULL,
	created_at timestamptz NOT NULL,
	updated_at timestamptz NOT NULL,
	student_id int8 NOT NULL,
	teacher_id int8 NOT NULL,
	lesson_type varchar(20) NOT NULL,
	student_rate numeric(6, 2) NOT NULL,
	teacher_rate numeric(6, 2) NOT NULL,
	is_trial bool NOT NULL,
	CONSTRAINT billing_lesson_pkey PRIMARY KEY (id),
	CONSTRAINT billing_lesson_student_id_7c8e5d9a_fk_billing_user_id FOREIGN KEY (student_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT billing_lesson_teacher_id_f3f4c0f7_fk_billing_user_id FOREIGN KEY (teacher_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX billing_lesson_student_id_7c8e5d9a ON public.billing_lesson USING btree (student_id);
CREATE INDEX billing_lesson_teacher_id_f3f4c0f7 ON public.billing_lesson USING btree (teacher_id);


-- public.billing_systemsettings definition

-- Drop table

-- DROP TABLE public.billing_systemsettings;

CREATE TABLE public.billing_systemsettings (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	invoice_recipient_email varchar(254) NOT NULL,
	updated_at timestamptz NOT NULL,
	updated_by_id int8 NULL,
	CONSTRAINT billing_systemsettings_pkey PRIMARY KEY (id),
	CONSTRAINT billing_systemsettin_updated_by_id_8e3a9c48_fk_billing_u FOREIGN KEY (updated_by_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX billing_systemsettings_updated_by_id_8e3a9c48 ON public.billing_systemsettings USING btree (updated_by_id);


-- public.billing_user_assigned_teachers definition

-- Drop table

-- DROP TABLE public.billing_user_assigned_teachers;

CREATE TABLE public.billing_user_assigned_teachers (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	from_user_id int8 NOT NULL,
	to_user_id int8 NOT NULL,
	CONSTRAINT billing_user_assigned_te_from_user_id_to_user_id_3bbe2a46_uniq UNIQUE (from_user_id, to_user_id),
	CONSTRAINT billing_user_assigned_teachers_pkey PRIMARY KEY (id),
	CONSTRAINT billing_user_assigne_from_user_id_22e57552_fk_billing_u FOREIGN KEY (from_user_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT billing_user_assigne_to_user_id_6669fe27_fk_billing_u FOREIGN KEY (to_user_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX billing_user_assigned_teachers_from_user_id_22e57552 ON public.billing_user_assigned_teachers USING btree (from_user_id);
CREATE INDEX billing_user_assigned_teachers_to_user_id_6669fe27 ON public.billing_user_assigned_teachers USING btree (to_user_id);


-- public.billing_user_groups definition

-- Drop table

-- DROP TABLE public.billing_user_groups;

CREATE TABLE public.billing_user_groups (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	user_id int8 NOT NULL,
	group_id int4 NOT NULL,
	CONSTRAINT billing_user_groups_pkey PRIMARY KEY (id),
	CONSTRAINT billing_user_groups_user_id_group_id_af6b9d11_uniq UNIQUE (user_id, group_id),
	CONSTRAINT billing_user_groups_group_id_2b1dc023_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT billing_user_groups_user_id_4385cb5c_fk_billing_user_id FOREIGN KEY (user_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX billing_user_groups_group_id_2b1dc023 ON public.billing_user_groups USING btree (group_id);
CREATE INDEX billing_user_groups_user_id_4385cb5c ON public.billing_user_groups USING btree (user_id);


-- public.billing_user_user_permissions definition

-- Drop table

-- DROP TABLE public.billing_user_user_permissions;

CREATE TABLE public.billing_user_user_permissions (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	user_id int8 NOT NULL,
	permission_id int4 NOT NULL,
	CONSTRAINT billing_user_user_permis_user_id_permission_id_78bf0dc2_uniq UNIQUE (user_id, permission_id),
	CONSTRAINT billing_user_user_permissions_pkey PRIMARY KEY (id),
	CONSTRAINT billing_user_user_pe_permission_id_0e45bb97_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT billing_user_user_pe_user_id_65bb214f_fk_billing_u FOREIGN KEY (user_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX billing_user_user_permissions_permission_id_0e45bb97 ON public.billing_user_user_permissions USING btree (permission_id);
CREATE INDEX billing_user_user_permissions_user_id_65bb214f ON public.billing_user_user_permissions USING btree (user_id);


-- public.billing_userregistrationrequest definition

-- Drop table

-- DROP TABLE public.billing_userregistrationrequest;

CREATE TABLE public.billing_userregistrationrequest (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	email varchar(254) NOT NULL,
	first_name varchar(150) NOT NULL,
	last_name varchar(150) NOT NULL,
	user_type varchar(20) NOT NULL,
	oauth_provider varchar(50) NOT NULL,
	oauth_id varchar(100) NOT NULL,
	status varchar(20) NOT NULL,
	requested_at timestamptz NOT NULL,
	reviewed_at timestamptz NULL,
	notes text NOT NULL,
	reviewed_by_id int8 NULL,
	CONSTRAINT billing_userregistrationrequest_email_key UNIQUE (email),
	CONSTRAINT billing_userregistrationrequest_pkey PRIMARY KEY (id),
	CONSTRAINT billing_userregistra_reviewed_by_id_81058627_fk_billing_u FOREIGN KEY (reviewed_by_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX billing_userregistrationrequest_email_93d1a3a2_like ON public.billing_userregistrationrequest USING btree (email varchar_pattern_ops);
CREATE INDEX billing_userregistrationrequest_reviewed_by_id_81058627 ON public.billing_userregistrationrequest USING btree (reviewed_by_id);


-- public.django_admin_log definition

-- Drop table

-- DROP TABLE public.django_admin_log;

CREATE TABLE public.django_admin_log (
	id int4 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 START 1 CACHE 1 NO CYCLE) NOT NULL,
	action_time timestamptz NOT NULL,
	object_id text NULL,
	object_repr varchar(200) NOT NULL,
	action_flag int2 NOT NULL,
	change_message text NOT NULL,
	content_type_id int4 NULL,
	user_id int8 NOT NULL,
	CONSTRAINT django_admin_log_action_flag_check CHECK ((action_flag >= 0)),
	CONSTRAINT django_admin_log_pkey PRIMARY KEY (id),
	CONSTRAINT django_admin_log_content_type_id_c4bce8eb_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT django_admin_log_user_id_c564eba6_fk_billing_user_id FOREIGN KEY (user_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX django_admin_log_content_type_id_c4bce8eb ON public.django_admin_log USING btree (content_type_id);
CREATE INDEX django_admin_log_user_id_c564eba6 ON public.django_admin_log USING btree (user_id);


-- public.socialaccount_socialaccount definition

-- Drop table

-- DROP TABLE public.socialaccount_socialaccount;

CREATE TABLE public.socialaccount_socialaccount (
	id int4 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 START 1 CACHE 1 NO CYCLE) NOT NULL,
	provider varchar(200) NOT NULL,
	uid varchar(191) NOT NULL,
	last_login timestamptz NOT NULL,
	date_joined timestamptz NOT NULL,
	extra_data jsonb NOT NULL,
	user_id int8 NOT NULL,
	CONSTRAINT socialaccount_socialaccount_pkey PRIMARY KEY (id),
	CONSTRAINT socialaccount_socialaccount_provider_uid_fc810c6e_uniq UNIQUE (provider, uid),
	CONSTRAINT socialaccount_socialaccount_user_id_8146e70c_fk_billing_user_id FOREIGN KEY (user_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX socialaccount_socialaccount_user_id_8146e70c ON public.socialaccount_socialaccount USING btree (user_id);


-- public.socialaccount_socialapp_sites definition

-- Drop table

-- DROP TABLE public.socialaccount_socialapp_sites;

CREATE TABLE public.socialaccount_socialapp_sites (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	socialapp_id int4 NOT NULL,
	site_id int4 NOT NULL,
	CONSTRAINT socialaccount_socialapp__socialapp_id_site_id_71a9a768_uniq UNIQUE (socialapp_id, site_id),
	CONSTRAINT socialaccount_socialapp_sites_pkey PRIMARY KEY (id),
	CONSTRAINT socialaccount_social_site_id_2579dee5_fk_django_si FOREIGN KEY (site_id) REFERENCES public.django_site(id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT socialaccount_social_socialapp_id_97fb6e7d_fk_socialacc FOREIGN KEY (socialapp_id) REFERENCES public.socialaccount_socialapp(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX socialaccount_socialapp_sites_site_id_2579dee5 ON public.socialaccount_socialapp_sites USING btree (site_id);
CREATE INDEX socialaccount_socialapp_sites_socialapp_id_97fb6e7d ON public.socialaccount_socialapp_sites USING btree (socialapp_id);


-- public.socialaccount_socialtoken definition

-- Drop table

-- DROP TABLE public.socialaccount_socialtoken;

CREATE TABLE public.socialaccount_socialtoken (
	id int4 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 START 1 CACHE 1 NO CYCLE) NOT NULL,
	"token" text NOT NULL,
	token_secret text NOT NULL,
	expires_at timestamptz NULL,
	account_id int4 NOT NULL,
	app_id int4 NULL,
	CONSTRAINT socialaccount_socialtoken_app_id_account_id_fca4e0ac_uniq UNIQUE (app_id, account_id),
	CONSTRAINT socialaccount_socialtoken_pkey PRIMARY KEY (id),
	CONSTRAINT socialaccount_social_account_id_951f210e_fk_socialacc FOREIGN KEY (account_id) REFERENCES public.socialaccount_socialaccount(id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT socialaccount_social_app_id_636a42d7_fk_socialacc FOREIGN KEY (app_id) REFERENCES public.socialaccount_socialapp(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX socialaccount_socialtoken_account_id_951f210e ON public.socialaccount_socialtoken USING btree (account_id);
CREATE INDEX socialaccount_socialtoken_app_id_636a42d7 ON public.socialaccount_socialtoken USING btree (app_id);


-- public.token_blacklist_outstandingtoken definition

-- Drop table

-- DROP TABLE public.token_blacklist_outstandingtoken;

CREATE TABLE public.token_blacklist_outstandingtoken (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	"token" text NOT NULL,
	created_at timestamptz NULL,
	expires_at timestamptz NOT NULL,
	user_id int8 NULL,
	jti varchar(255) NOT NULL,
	CONSTRAINT token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_uniq UNIQUE (jti),
	CONSTRAINT token_blacklist_outstandingtoken_pkey PRIMARY KEY (id),
	CONSTRAINT token_blacklist_outs_user_id_83bc629a_fk_billing_u FOREIGN KEY (user_id) REFERENCES public.billing_user(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_like ON public.token_blacklist_outstandingtoken USING btree (jti varchar_pattern_ops);
CREATE INDEX token_blacklist_outstandingtoken_user_id_83bc629a ON public.token_blacklist_outstandingtoken USING btree (user_id);


-- public.auth_group_permissions definition

-- Drop table

-- DROP TABLE public.auth_group_permissions;

CREATE TABLE public.auth_group_permissions (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	group_id int4 NOT NULL,
	permission_id int4 NOT NULL,
	CONSTRAINT auth_group_permissions_group_id_permission_id_0cd325b0_uniq UNIQUE (group_id, permission_id),
	CONSTRAINT auth_group_permissions_pkey PRIMARY KEY (id),
	CONSTRAINT auth_group_permissio_permission_id_84c5c92e_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT auth_group_permissions_group_id_b120cbf9_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX auth_group_permissions_group_id_b120cbf9 ON public.auth_group_permissions USING btree (group_id);
CREATE INDEX auth_group_permissions_permission_id_84c5c92e ON public.auth_group_permissions USING btree (permission_id);


-- public.billing_invoice_lessons definition

-- Drop table

-- DROP TABLE public.billing_invoice_lessons;

CREATE TABLE public.billing_invoice_lessons (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	invoice_id int8 NOT NULL,
	lesson_id int8 NOT NULL,
	CONSTRAINT billing_invoice_lessons_invoice_id_lesson_id_674d6655_uniq UNIQUE (invoice_id, lesson_id),
	CONSTRAINT billing_invoice_lessons_pkey PRIMARY KEY (id),
	CONSTRAINT billing_invoice_less_invoice_id_a7cf869f_fk_billing_i FOREIGN KEY (invoice_id) REFERENCES public.billing_invoice(id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT billing_invoice_lessons_lesson_id_37afa789_fk_billing_lesson_id FOREIGN KEY (lesson_id) REFERENCES public.billing_lesson(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX billing_invoice_lessons_invoice_id_a7cf869f ON public.billing_invoice_lessons USING btree (invoice_id);
CREATE INDEX billing_invoice_lessons_lesson_id_37afa789 ON public.billing_invoice_lessons USING btree (lesson_id);


-- public.token_blacklist_blacklistedtoken definition

-- Drop table

-- DROP TABLE public.token_blacklist_blacklistedtoken;

CREATE TABLE public.token_blacklist_blacklistedtoken (
	id int8 GENERATED BY DEFAULT AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	blacklisted_at timestamptz NOT NULL,
	token_id int8 NOT NULL,
	CONSTRAINT token_blacklist_blacklistedtoken_pkey PRIMARY KEY (id),
	CONSTRAINT token_blacklist_blacklistedtoken_token_id_key UNIQUE (token_id),
	CONSTRAINT token_blacklist_blacklistedtoken_token_id_3cc7fe56_fk FOREIGN KEY (token_id) REFERENCES public.token_blacklist_outstandingtoken(id) DEFERRABLE INITIALLY DEFERRED
);