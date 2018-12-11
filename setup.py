from setuptools import setup

setup(name = "py-opensmtpd-rspamd",
      version = "0.0.1",
      description = "py-opensmtpd-rspamd is an Rspamd filter for the OpenSMTPD MTA",
      author = "Gilles Chehade",
      author_email = "gilles@poolp.org",
      packages = [ "opensmtpd_rspamd" ],
      scripts = [
          "scripts/filter-rspamd",
      ],
      install_requires=[
          "requests",
      ]
)
