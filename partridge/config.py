'''
Global configuration module for Partridge

'''

import json


class Config:
  
  def load(self, conffile):
    with open(conffile,'r') as f:
      config = json.load(f)

      for k in config.keys():
        self.__dict__[k] = config[k]


config = Config()

for loc in (os.curdir, 
  os.path.expanduser("~/.config/"), "/etc/", 
  os.environ.get("PARTRIDGE_CONF")):
          try: 
              config.load(source)
          except IOError:
              pass
