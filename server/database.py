import sqlalchemy
    
from sqlalchemy.ext.declarative import declarative_base
Base = declarative_base()

from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import sessionmaker, relationship

class CallStack(Base):
    __tablename__ = 'call_stacks'
    id = Column(Integer, primary_key=True)
    datetime = Column(Float)
    total_time = Column(Float)
    
    call_stack_items = relationship("CallStackItem", cascade="all", backref='call_stacks')
  
    def __init__(self, profile_stats):
        self.datetime = profile_stats['datetime']
        self.total_time = profile_stats['total_time']
      
    def __repr__(self):
        return str(self.id)

class CallStackItem(Base):
    __tablename__ = 'call_stack_items'
    id = Column(Integer, primary_key=True)
    call_stack_id = Column(None, ForeignKey('call_stacks.id'))
    function_name = Column(String)
    line_number = Column(Integer)
    module = Column(String)
    total_calls = Column(Integer)
    native_calls = Column(Integer)
    cumulative_time = Column(Float)
    total_time = Column(Float)
  
    def __init__(self, call_stack_id, stats):
        self.call_stack_id = call_stack_id
        self.function_name = stats['function']['name']
        self.line_number = stats['function']['line']
        self.module = stats['function']['module']
        self.total_calls = stats['total_calls']
        self.native_calls = stats['native_calls']
        self.cumulative_time = stats['cumulative']
        self.total_time = stats['time']
      
    def __repr__(self):
        return ""

class SQLStatement(Base):
    __tablename__ = 'sql_statements'
    id = Column(Integer, primary_key=True)
    sql_string = Column(String)
    datetime = Column(Float)
    duration = Column(Float)
  
    def __init__(self, profile_stats):
        self.sql_string = profile_stats['sql']
        self.datetime = profile_stats['datetime']
        self.duration = profile_stats['duration']
      
    def __repr__(self):
        return self.sql_string

class MetaData(Base):
    __tablename__ = 'metadata'
    id = Column(Integer, primary_key=True)
    key = Column(String)
    value = Column(String)
  
    def __init__(self, key, value):
        self.key = key
        self.value = value
        
class CallStackMetadata(Base):
    __tablename__ = 'call_stack_metadata'
    id = Column(Integer, primary_key=True)
    call_stack_id = Column(None, ForeignKey('call_stacks.id'))
    metadata_id = Column(None, ForeignKey('metadata.id'))
  
    def __init__(self, call_stack_id, metadata_id):
        self.call_stack_id = call_stack_id
        self.metadata_id = metadata_id
        
class SQLStatementMetadata(Base):
    __tablename__ = 'sql_statement_metadata'
    id = Column(Integer, primary_key=True)
    sql_statement_id = Column(None, ForeignKey('sql_statements.id'))
    metadata_id = Column(None, ForeignKey('metadata.id'))
  
    def __init__(self, sql_statement_id, metadata_id):
        self.sql_statement_id = sql_statement_id
        self.metadata_id = metadata_id

def create_db_and_connect(postgres_string):
    database = sqlalchemy.create_engine(postgres_string + '/profile_stats')
    database.connect()
    return database

session = None

def setup_profile_database(username, password):
    postgres_string = 'postgresql://' + username + ':' + password + '@localhost'
    try:
        db = create_db_and_connect(postgres_string)
    except:
        postgres = sqlalchemy.create_engine(postgres_string + '/postgres')
        conn = postgres.connect()
        conn.execute('commit')
        conn.execute('create database profile_stats')
        conn.close()
        db = create_db_and_connect(postgres_string)
        
    Base.metadata.create_all(db)
    Session = sessionmaker(bind=db)
    global session
    session = Session()

sender_metadata_keys = ['exhibitor_chain','exhibitor_branch','product','version']
method_call_metadata_keys = ['function','class','module']

def get_metadata_list(metadata_dictionary, metadata_keys):
    metadata_list = []
    for metadata_key in metadata_keys:
        metadata_query = session.query(MetaData).filter_by(key=metadata_key, value=metadata_dictionary[metadata_key])
        if metadata_query.count() == 0:
            # Add new metadata if does not exist
            metadata = MetaData(metadata_key, metadata_dictionary[metadata_key])
            metadata_list.append(metadata)
            session.add(metadata)
            session.commit()
        else:
            metadata_list.append(metadata_query.first())
    return metadata_list

def push_fn_stats(stats_packet, ip_address):
    # Add sender metadata
    sender_metadata_list = get_metadata_list(stats_packet, sender_metadata_keys)
    for sender_metadata in sender_metadata_list:
        session.add(sender_metadata)
    
    for profile_stats in stats_packet['stats']:
        # Add function metadata
        function_metadata_list = get_metadata_list(profile_stats, method_call_metadata_keys)
        for function_metadata in function_metadata_list:
            session.add(function_metadata)
            
        # Add call stack
        call_stack = CallStack(profile_stats)
        session.add(call_stack)
        session.commit()
        
        # Add call stack/metadata relationships
        for sender_metadata in sender_metadata_list:
            session.add(CallStackMetadata(call_stack.id, sender_metadata.id))
        for function_metadata in function_metadata_list:
            session.add(CallStackMetadata(call_stack.id, function_metadata.id))
        
        # Add call stack items
        pstats = profile_stats['pstats']
        for stats in pstats:
            session.add(CallStackItem(call_stack.id, stats))
    session.commit()

def push_sql_stats(stats_packet, ip_address):
    # Add sender metadata
    sender_metadata_list = get_metadata_list(stats_packet, sender_metadata_keys)
    for sender_metadata in sender_metadata_list:
        session.add(sender_metadata)
    
    for sql_stat in stats_packet['stats']:
        # Add sql statement
        sql_statement = SQLStatement(sql_stat)
        session.add(sql_statement)
        session.commit()
        
        # Add sql statement/metadata relationships
        for sender_metadata in sender_metadata_list:
            session.add(SQLStatementMetadata(sql_statement.id, sender_metadata.id))
    session.commit()
