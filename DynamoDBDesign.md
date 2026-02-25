**DynamoDB Design Solutions**

*Chapters 15--22 \| The DynamoDB Book*

Migration Patterns · Design Strategies · Real-World Case Studies

  -----------------------------------------------------------------------
  *This document covers every key pattern, rule, and design decision from
  Chapters 15--22 of The DynamoDB Book. Content is extracted directly
  from the book without hallucination. Each section is grounded in the
  book\'s examples: e-commerce, deals platform, GitHub clone, and GitHub
  migration.*

  -----------------------------------------------------------------------

**Part I --- Master Design Principles**

The following principles are drawn directly from the book\'s guidance
across Chapters 7, 9, 15, 17, and the case studies. These are not
abstractions --- they are the actual rules the book instructs developers
to follow.

**Rule 1: Know Your Access Patterns Before Modeling**

DynamoDB is not flexible like a relational database. Its power comes
from knowing exactly how data will be accessed upfront and designing the
table to serve those patterns directly. Model your table to match your
access patterns --- not the other way around.

-   Create an ERD first to understand entity relationships

-   List every access pattern explicitly before writing any key patterns

-   For each access pattern, determine: what is the partition key? what
    is the sort key? which index?

-   Do NOT model DynamoDB like a relational database with normalized
    tables

**Rule 2: Start Every Model with Three Questions**

The book instructs developers to ask these three questions at the start
of every data modeling exercise:

  ---------------------------------------------------------------------------------
  **Question**         **Guidance from the Book**
  -------------------- ------------------------------------------------------------
  1\. Simple or        Use composite (PK+SK) for any table with \>1 entity type,
  composite primary    fetch-many patterns, or relationships between entities.
  key?                 Simple keys only work for a single entity with pure
                       key-value lookups (e.g., Session Store).

  2\. What are the     Look for: uniqueness constraints on multiple attributes,
  interesting/unique   time-based ordering, filtering requirements, hot key
  requirements?        concerns, \'fetch parent + children\' patterns. These drive
                       your GSI design.

  3\. Which entity to  Start with the \'core\' entity --- typically the parent in
  model first?         the most relationships, or the entity with the most access
                       patterns. Build outward from there.
  ---------------------------------------------------------------------------------

**Rule 3: Use the Standard Modeling Process**

  ------------------------------------------------------------------------------
  **Step**   **Action**                  **Output**
  ---------- --------------------------- ---------------------------------------
  1          Understand the application  Problem statement
             --- screens, constraints,   
             business rules              

  2          Create an ERD --- entities  ERD diagram
             and relationships only (no  
             attributes needed)          

  3          Build an entity chart ---   Entity chart template
             list every entity with      
             blank PK/SK columns         

  4          List all access patterns    Access pattern list
             --- group by feature area,  
             skip trivial CRUD           

  5          Design primary key + GSIs   Completed entity charts
             --- fill in the entity      
             chart                       

  6          Validate --- trace every    Verified design
             access pattern through the  
             model                       
  ------------------------------------------------------------------------------

**Rule 4: Understand the Two Types of Attributes**

  -----------------------------------------------------------------------
  **Attribute      **Definition**             **Impact on Modeling**
  Type**                                      
  ---------------- -------------------------- ---------------------------
  Indexing         PK, SK, GSI1PK, GSI1SK,    Must be designed carefully
  Attributes       etc. --- attributes used   upfront. Changing these
                   for data access in         requires migrations.
                   DynamoDB                   

  Application      Username, Name, CreatedAt, Schemaless --- can be added
  Attributes       etc. --- data the          or changed at any time with
                   application uses after     no DynamoDB changes.
                   fetching                   
  -----------------------------------------------------------------------

  -----------------------------------------------------------------------
  *💡 Key insight: Only indexing attributes require careful upfront
  design. Application attributes are free to add or change at any time in
  your application code. This distinction is fundamental to understanding
  migrations.*

  -----------------------------------------------------------------------

**Rule 5: Pre-Join Data Using Item Collections**

DynamoDB has no JOIN operation. Instead, design item collections that
co-locate related data in the same partition. The Query API can then
fetch multiple entity types in a single request.

-   Place parent and related child entities in the same partition key

-   Use the sort key to distinguish entity types (e.g., CUSTOMER#\<id\>
    vs #ORDER#\<ksuid\>)

-   Use \# prefix on sort keys to control ordering --- \# sorts before
    letters, allowing parent to appear at top or bottom

-   Model up to two one-to-many relationships in a single item
    collection by placing the parent in the middle of the sort key range

**Rule 6: Choose Primary Key Names Intentionally**

  ------------------------------------------------------------------------
  **Scenario**          **Recommendation**    **Example**
  --------------------- --------------------- ----------------------------
  Single entity type in Use descriptive names SessionToken, Username
  table                                       

  Multiple entity types Use generic names     PK, SK, GSI1PK, GSI1SK
  (single-table design)                       

  GSI keys              Always generic        GSI1PK, GSI1SK, GSI2PK,
                                              GSI2SK
  ------------------------------------------------------------------------

**Part II --- Migration Patterns (Chapter 15 & 22)**

Migrations are the set of changes required when your access patterns
evolve. The book classifies migrations by difficulty and provides
concrete strategies for each. Chapter 22 applies these strategies to the
GitHub data model.

**The Migration Decision Tree**

Always ask: Is this change purely additive, or does it require editing
existing items?

  ----------------------------------------------------------------------------------
  **Situation**         **Additive?**   **Requires   **Strategy**
                                        Batch Job?** 
  --------------------- --------------- ------------ -------------------------------
  Adding a new          Yes             No           Lazy loading --- add defaults
  application attribute                              in application code when
  (e.g., Birthdate,                                  transforming DynamoDB items
  FaxNumber)                                         into domain objects

  Adding a new entity   Yes             No           Start writing new items
  with no relational                                 directly. No changes to
  access pattern                                     existing items needed.

  New entity that fits  Yes             No           Model new entity\'s PK/SK to
  into an existing item                              co-locate with existing items.
  collection                                         No ETL required.

  New entity requiring  No              Yes          Run Scan + UpdateItem batch job
  a new item collection                              to decorate existing parent
  in a GSI                                           items with new GSI attributes.
                                                     Use parallel scans to speed up.

  Joining existing      No              Yes          Same as above --- find items to
  items into a new item                              update, design new GSI, run
  collection                                         batch update.

  Refactoring an        No              Yes          Redesign the key pattern, run
  existing access                                    Scan + UpdateItem to add new
  pattern (e.g., filter                              attributes, add new GSIs.
  expression → sort key                              
  design)                                            
  ----------------------------------------------------------------------------------

**Migration Pattern 1: Adding New Application Attributes**

**When to use**

You want to add a new optional attribute to an existing entity (e.g.,
adding Birthdate to Users, adding CodeOfConduct to Repos).

**Design approach**

-   Do NOT run any ETL job on your DynamoDB table

-   Update your application code to handle the missing attribute
    gracefully with a default value

-   New items will have the attribute; old items will have it lazily
    populated

> def get_user(username):
>
> resp = client.get_item(TableName=\'AppTable\', Key={\'PK\':
> f\'USER#{username}\'})
>
> return User(
>
> username=item\[\'Username\'\]\[\'S\'\],
>
> birthdate=item.get(\'Birthdate\', {}).get(\'S\') \# handles missing
> attribute
>
> )

  -----------------------------------------------------------------------
  *✅ From Chapter 22 (GitHub example): The Code of Conduct entity was
  added this way. Since it\'s a one-to-one attribute stored on the Repo
  item, no ETL was needed --- just add it lazily as users register codes
  of conduct.*

  -----------------------------------------------------------------------

**Migration Pattern 2: New Entity Without Relational Access Pattern**

**When to use**

You have a new entity type, but there is no access pattern requiring it
to be fetched alongside an existing parent entity.

**Design approach**

-   Create a new item collection with a fresh partition key structure

-   Start writing new items immediately --- zero changes to existing
    data

-   Update only your application code

  -----------------------------------------------------------------------------
  **Entity**      **PK**              **SK**                  **Notes**
  --------------- ------------------- ----------------------- -----------------
  Organization    ORG#\<OrgId\>       ORG#\<OrgId\>           No change
  (existing)                                                  

  User (existing) ORG#\<OrgId\>       USER#\<Username\>       No change

  Project (new)   PROJECT#\<OrgId\>   PROJECT#\<ProjectId\>   New independent
                                                              collection
  -----------------------------------------------------------------------------

**Migration Pattern 3: New Entity into an Existing Item Collection**

**When to use**

You have a new entity AND a relational access pattern (e.g., \'fetch
Post and its Likes\'). The parent\'s item collection in the base table
has space available (i.e., no other relationship is using it).

**Design approach**

-   Model the new entity\'s PK to match the parent\'s PK --- this places
    them in the same item collection

-   Use a distinct SK prefix to identify the entity type

-   Purely additive --- no changes to existing items

  ------------------------------------------------------------------------
  **Entity**      **PK**             **SK**              **Result**
  --------------- ------------------ ------------------- -----------------
  Post (existing) POST#\<PostId\>    POST#\<PostId\>     Unchanged

  Like (new)      POST#\<PostId\>    LIKE#\<Username\>   Co-located with
                                                         Post
  ------------------------------------------------------------------------

  -----------------------------------------------------------------------
  *✅ From Chapter 22 (GitHub example): Gists were added this way. The
  User item collection in the base table was not being used for any other
  relationship, so Gist items were placed there using SK:
  #GIST#\<KSUID\>.*

  -----------------------------------------------------------------------

**Migration Pattern 4: New Entity Requiring a New Item Collection**

**When to use**

You have a new entity AND a relational access pattern, but the parent\'s
item collection in the base table is already in use for another
relationship. You must create a new item collection in a GSI.

**Design approach --- 3 steps**

-   Step 1: Design new GSI attributes on both the parent item and the
    new child item

-   Step 2: Run a Scan + UpdateItem batch job to add GSI attributes to
    all existing parent items

-   Step 3: New child items automatically include the GSI attributes
    when created

**Example: Adding Comments to Posts (when Post\'s base table collection
is already used for Likes)**

  ------------------------------------------------------------------------------------------------------
  **Entity**   **PK**                  **SK**                  **GSI1PK**        **GSI1SK**
  ------------ ----------------------- ----------------------- ----------------- -----------------------
  Post         POST#\<PostId\>         POST#\<PostId\>         POST#\<PostId\>   POST#\<PostId\> (NEW)
  (existing)                                                   (NEW)             

  Like         POST#\<PostId\>         LIKE#\<Username\>       (none)            (none)
  (existing)                                                                     

  Comment      COMMENT#\<CommentId\>   COMMENT#\<CommentId\>   POST#\<PostId\>   COMMENT#\<Timestamp\>
  (new)                                                                          
  ------------------------------------------------------------------------------------------------------

**Batch update script for existing Post items:**

> last_evaluated = \'\'
>
> params = {
>
> \'TableName\': \'SocialNetwork\',
>
> \'FilterExpression\': \'#type = :type\',
>
> \'ExpressionAttributeNames\': { \'#type\': \'Type\' },
>
> \'ExpressionAttributeValues\': { \':type\': { \'S\': \'Post\' } }
>
> }
>
> while True:
>
> if last_evaluated: params\[\'ExclusiveStartKey\'\] = last_evaluated
>
> results = client.scan(\*\*params)
>
> for item in results\[\'Items\'\]:
>
> client.update_item(
>
> TableName=\'SocialNetwork\',
>
> Key={ \'PK\': item\[\'PK\'\], \'SK\': item\[\'SK\'\] },
>
> UpdateExpression=\'SET #gsi1pk = :gsi1pk, #gsi1sk = :gsi1sk\',
>
> ExpressionAttributeNames={ \'#gsi1pk\': \'GSI1PK\', \'#gsi1sk\':
> \'GSI1SK\' },
>
> ExpressionAttributeValues={ \':gsi1pk\': item\[\'PK\'\], \':gsi1sk\':
> item\[\'SK\'\] }
>
> )
>
> if not results.get(\'LastEvaluatedKey\'): break
>
> last_evaluated = results\[\'LastEvaluatedKey\'\]

  -----------------------------------------------------------------------
  *✅ From Chapter 22 (GitHub example): GitHub Apps required this
  pattern. User and Org items were batch-updated with GSI1PK and GSI1SK
  attributes to create an item collection in GSI1 alongside GitHub App
  items.*

  -----------------------------------------------------------------------

**Migration Pattern 5: Using Parallel Scans**

For large tables, use DynamoDB\'s built-in parallel scan to dramatically
speed up ETL jobs.

> params = {
>
> \'TableName\': \'GitHubModel\',
>
> \'FilterExpression\': \'#type IN (:user, :org)\',
>
> \...
>
> \'TotalSegments\': 10, \# Split across 10 workers
>
> \'Segment\': 0 \# This worker processes segment 0 (of 0--9)
>
> }

  -----------------------------------------------------------------------
  *💡 DynamoDB handles all state management. Each worker runs
  independently. No manual coordination needed. Run all N workers
  simultaneously to achieve full parallelism.*

  -----------------------------------------------------------------------

**Migration Ranking: Easiest to Hardest**

From Chapter 22, the book explicitly ranks migration types by
difficulty:

  -----------------------------------------------------------------------------
  **Rank**    **Migration Type**           **Effort**
  ----------- ---------------------------- ------------------------------------
  1 (Easiest) Adding a new attribute or    Lazy loading --- no DynamoDB changes
              one-to-one relationship      

  2           New entity with no           Write new items --- no ETL needed
              relationship                 

  3           New entity into an existing  Model key pattern --- no ETL needed
              item collection              

  4           New entity into a new item   Scan + UpdateItem ETL batch job
              collection                   required

  5 (Hardest) Refactoring an existing      ETL + new GSI(s) + application code
              access pattern               changes
  -----------------------------------------------------------------------------

**Part III --- Patterns for Adding New Entities**

When adding a new entity, the core question is always: does this entity
have a relational access pattern that requires co-locating it with an
existing entity?

**Decision Framework: Where to Place a New Entity**

  -----------------------------------------------------------------------
  **Relational Access **Existing          **Solution**
  Pattern?**          Collection          
                      Available?**        
  ------------------- ------------------- -------------------------------
  No                  N/A                 Create a new independent item
                                          collection. Start writing
                                          immediately.

  Yes --- fetch       Yes --- parent\'s   Place new entity in parent\'s
  parent + children   collection is       existing item collection. Match
                      unused              the parent PK.

  Yes --- fetch       No --- parent\'s    Create a new item collection in
  parent + children   collection is       a GSI. Add GSI attributes to
                      occupied            parent via batch job.

  Yes ---             N/A                 Use adjacency list pattern.
  many-to-many                            Create an AppInstallation-style
                                          item that lives in both
                                          collections.
  -----------------------------------------------------------------------

**Pattern: One-to-One Relationship → Attribute on Parent Item**

A one-to-one relationship is almost always stored as a complex attribute
(map) on the parent item. Split it out into a separate item only if it
is very large or accessed separately.

-   Example: Payment Plan on User/Organization --- stored as PaymentPlan
    attribute (map) on the User/Org item

-   Example: Code of Conduct on Repo --- stored as CodeOfConduct
    attribute (map) on the Repo item

  -----------------------------------------------------------------------
  *✅ Pattern from Chapter 21 and 22: \'When you have a one-to-one
  relationship in DynamoDB, you almost always include that information
  directly on the parent item.\'*

  -----------------------------------------------------------------------

**Pattern: One-to-Many (bounded) → Denormalization / Complex Attribute**

If the number of related items is bounded (you can set a reasonable
limit), store them as a complex attribute (map or list) on the parent
item. This eliminates the need for a separate item type.

-   Example: Addresses on Customer --- stored as Addresses map attribute
    on Customer item (bounded to \~20)

-   Example: Featured Deals on Category --- stored as FeaturedDeals
    complex attribute on Category item (limited to 5--10)

-   Example: Organizations on User --- stored as Organizations map
    attribute on User item (bounded to \~40)

-   Two denormalization questions to ask: (1) Is there a direct access
    pattern for the related entity outside the parent context? (2) Is
    the data unbounded?

  -----------------------------------------------------------------------
  *⚠️ Only use this if both answers are NO. If data is unbounded (e.g.,
  orders, issues), you MUST use the primary key + Query strategy
  instead.*

  -----------------------------------------------------------------------

**Pattern: One-to-Many (unbounded) → Primary Key + Query**

If the number of related items is unbounded, co-locate them with the
parent in the same partition key. Use the sort key to distinguish entity
types and enable the Query API.

  ------------------------------------------------------------------------------------------
  **Entity**      **PK**                        **SK**                       **Notes**
  --------------- ----------------------------- ---------------------------- ---------------
  Customer        CUSTOMER#\<Username\>         CUSTOMER#\<Username\>        Parent

  Order           CUSTOMER#\<Username\>         #ORDER#\<KSUID\>             \# prefix
                                                                             places Order
                                                                             before Customer
                                                                             in sort order

  Issue (GitHub)  REPO#\<Owner\>#\<RepoName\>   ISSUE#\<ZeroPaddedNumber\>   Zero-padding
                                                                             required for
                                                                             correct
                                                                             lexicographic
                                                                             sort
  ------------------------------------------------------------------------------------------

-   Use ScanIndexForward=False to fetch parent + most recent children in
    one Query

-   The \# prefix on child SK items causes them to sort before the
    parent, enabling reverse-order fetching

-   Use KSUIDs as identifiers when chronological ordering is needed

-   Zero-pad numeric identifiers (e.g., issue numbers) to ensure correct
    lexicographic ordering

**Pattern: Many-to-Many → Adjacency List**

For many-to-many relationships, create a separate \'link\' item that
belongs to both parent item collections. Use a GSI to project the link
item into the second parent\'s collection.

  ----------------------------------------------------------------------------------------------------------------------------------------------------------
  **Entity**        **PK**                            **SK**                            **GSI1PK**                        **GSI1SK**
  ----------------- --------------------------------- --------------------------------- --------------------------------- ----------------------------------
  GitHubApp         APP#\<AccountName\>#\<AppName\>   APP#\<AccountName\>#\<AppName\>   ACCOUNT#\<AccountName\>           APP#\<AppName\>

  AppInstallation   APP#\<AccountName\>#\<AppName\>   REPO#\<RepoOwner\>#\<RepoName\>   REPO#\<RepoOwner\>#\<RepoName\>   REPOAPP#\<AppOwner\>#\<AppName\>

  Repo              REPO#\<Owner\>#\<RepoName\>       REPO#\<Owner\>#\<RepoName\>       REPO#\<Owner\>#\<RepoName\>       REPO#\<Owner\>#\<RepoName\>
  ----------------------------------------------------------------------------------------------------------------------------------------------------------

-   Base table: AppInstallation is in the same partition as its GitHub
    App → fetch App + all installations

-   GSI1: AppInstallation is in the same partition as its Repo → fetch
    Repo + all installed apps

-   The link item\'s PK and SK determine which side of the relationship
    lives in the base table

-   The GSI attributes put the link item in the other parent\'s
    partition

**Pattern: Shared Namespace → Unified Primary Key**

When two entity types compete for the same namespace (e.g., GitHub Users
and Organizations both need unique account names), give them the same
primary key structure. Distinguish them with a Type attribute.

  --------------------------------------------------------------------------------
  **Entity**      **PK**                 **SK**                 **Type attribute**
  --------------- ---------------------- ---------------------- ------------------
  User            ACCOUNT#\<Username\>   ACCOUNT#\<Username\>   Type: \'User\'

  Organization    ACCOUNT#\<OrgName\>    ACCOUNT#\<OrgName\>    Type:
                                                                \'Organization\'
  --------------------------------------------------------------------------------

  -----------------------------------------------------------------------
  *✅ From Chapter 21: \'Names are unique across organizations and users.
  There cannot be an organization with the same name as a user and vice
  versa.\' Using ACCOUNT# prefix enforces this at the DynamoDB level.*

  -----------------------------------------------------------------------

**Part IV --- Patterns for Adding New Attributes**

**Application Attributes --- Add Anytime, No Migration Needed**

DynamoDB\'s schemaless nature means you can add application attributes
to existing entities at any time without touching your DynamoDB table.
Handle missing attributes in your application code.

-   Add the attribute handling in your data access layer when
    transforming DynamoDB items to domain objects

-   Use item.get(\'AttributeName\', default) patterns to handle existing
    items without the attribute

-   New items will have the attribute; old items get the default until
    they are updated

-   This works for simple attributes AND complex attributes (maps, sets,
    lists)

**Indexing Attributes --- Require Migration Planning**

If a new attribute needs to be used for querying (as a GSI partition key
or sort key), this is a true migration. Follow Migration Pattern 4:
batch Scan + UpdateItem to add the attribute to existing items.

**Special Attribute: TTL**

Add a TTL attribute (epoch timestamp) to any item you want DynamoDB to
automatically expire. Keep a separate human-readable timestamp (ISO8601)
for application use.

  ------------------------------------------------------------------------
  **Attribute**   **Format**                  **Purpose**
  --------------- --------------------------- ----------------------------
  ExpiresAt       ISO8601 string              Human-readable --- used by
                  (2024-01-22T10:30:00Z)      application for
                                              display/debugging

  TTL             Epoch integer (1705916200)  DynamoDB TTL --- triggers
                                              automatic item deletion
  ------------------------------------------------------------------------

  -----------------------------------------------------------------------
  *⚠️ DynamoDB TTL deletes items within 48 hours of expiry (usually much
  faster). Use a FilterExpression on TTL \> current_epoch when reading to
  immediately reject recently expired items that haven\'t been deleted
  yet.*

  -----------------------------------------------------------------------

**Special Attribute: Reference Counts**

When you need to display a count of related items (e.g., star count,
fork count, like count), store a running count on the parent item. Never
query and count child items at read time.

-   Use a DynamoDB Transaction to atomically: (1) Create/validate the
    child item, and (2) Increment the counter on the parent

-   The transaction ensures the counter only increments when a genuinely
    new relationship is created

-   Used in: GitHub StarCount, ForkCount, BrandLikeCount,
    BrandWatchCount, CategoryLikeCount

> result = dynamodb.transact_write_items(TransactItems=\[
>
> { \'Put\': { \'Item\': { \'PK\': \'STAR#\...\' },
> \'ConditionExpression\': \'attribute_not_exists(PK)\' } },
>
> { \'Update\': { \'Key\': { \'PK\': \'REPO#\...\' },
>
> \'UpdateExpression\': \'SET #count = #count + :incr\',
>
> \'ExpressionAttributeValues\': { \':incr\': { \'N\': \'1\' } } } }
>
> \])

**Special Attribute: Sparse Index Trigger**

Selectively add a GSI attribute to only some items of a type to create a
sparse index. Items without the GSI attribute are excluded from the
index automatically.

-   Example: Unread Messages --- GSI1PK/GSI1SK only set on unread
    messages. When marked read, REMOVE these attributes.

-   Example: User Index --- UserIndex attribute only on User items. Used
    to project just Users into a separate index for \'find all users\'
    pattern.

> \# Mark message as read: remove GSI attributes
>
> client.update_item(
>
> UpdateExpression=\'SET #unread = :false, REMOVE #gsi1pk, #gsi1sk\',
>
> \...
>
> )

**Part V --- Best Practices for Designing a DynamoDB Table**

The following practices are drawn from across Chapters 7, 9, 14, 15, 16,
and the four case studies. These are the consistent patterns the book
demonstrates across all examples.

**1. Always Use Single-Table Design for Related Entities**

Store multiple entity types in a single DynamoDB table. Use generic
PK/SK attribute names (PK, SK) and create item collections that group
related entities together. This enables \'pre-joined\' queries.

  -----------------------------------------------------------------------
  *The book demonstrates single-table design in every case study:
  e-commerce (Customers + Orders + OrderItems), Big Time Deals (Deals +
  Brands + Categories + Users + Messages), and GitHub (10+ entity types
  in one table).*

  -----------------------------------------------------------------------

**2. Choose Identifiers That Support Your Access Patterns**

  ------------------------------------------------------------------------
  **Identifier       **When to Use**        **Example**
  Type**                                    
  ------------------ ---------------------- ------------------------------
  Username /         When the value itself  CUSTOMER#alexdebrie
  meaningful name    is the lookup key      

  KSUID              When you need          ORDER#\<ksuid\>,
                     chronological          GIST#\<ksuid\>
                     ordering + uniqueness  

  UUID               When you need          SessionToken
                     uniqueness without     
                     ordering               

  Zero-padded        When sequential IDs    ISSUE#00000015, PR#00000874
  integer            required and used in a 
                     sort key string        

  Integer difference When you need reverse  ISSUE#OPEN#99999984 (for issue
  (max - actual)     ordering on a forward  #15)
                     scan                   
  ------------------------------------------------------------------------

**3. Always Include Entity Type Prefix in PK/SK Values**

Prefix all key values with the entity type to prevent collisions and
enable filtering. This is consistent across all four case studies.

  -------------------------------------------------------------------------------------
  **Entity**      **PK Pattern**                     **SK Pattern**
  --------------- ---------------------------------- ----------------------------------
  Customer        CUSTOMER#\<Username\>              CUSTOMER#\<Username\>

  Order           CUSTOMER#\<Username\>              #ORDER#\<KSUID\>

  Repo            REPO#\<Owner\>#\<RepoName\>        REPO#\<Owner\>#\<RepoName\>

  Issue           REPO#\<Owner\>#\<RepoName\>        ISSUE#\<ZeroPaddedNumber\>

  BrandLike       BRANDLIKE#\<Brand\>#\<Username\>   BRANDLIKE#\<Brand\>#\<Username\>

  BrandWatch      BRANDWATCH#\<Brand\>               USER#\<Username\>
  -------------------------------------------------------------------------------------

**4. Use Composite Sort Keys for Multi-Dimensional Filtering**

When you need to filter on multiple attributes (e.g., Status AND Order),
combine them into the sort key using a composite pattern. This enables
efficient range queries without filter expressions.

-   Pattern: SK = PREFIX#\<FilterValue\>#\<SortValue\>

-   Example: ISSUE#CLOSED#\<IssueNumber\> and
    ISSUE#OPEN#\<IssueNumberDifference\>

-   This supports: \'fetch all open issues in reverse order\' and
    \'fetch all closed issues in order\' using two separate GSIs

-   The \# prefix separator is critical --- it creates consistent
    lexicographic grouping

**5. Use DynamoDB Transactions for Consistency**

Any time two writes must succeed or fail together, use
TransactWriteItems. Common use cases from the book:

  -----------------------------------------------------------------------
  **Use Case**             **Operations in Transaction**
  ------------------------ ----------------------------------------------
  Create user with unique  PutItem(User) with condition +
  username + email         PutItem(UserEmail) with condition

  Like a                   PutItem(Like) with condition +
  brand/repo/category      UpdateItem(LikeCount++) on parent

  Watch a brand/category   PutItem(Watch) with condition +
                           UpdateItem(WatchCount++) on parent

  Add reaction             UpdateItem(Reactions set) with condition +
                           UpdateItem(ReactionCount) on target

  Star a repo              PutItem(Star) with condition +
                           UpdateItem(StarCount++) on Repo

  Start a background job   UpdateItem(singleton) with condition (if count
                           \< 100) + UpdateItem(job status)
  -----------------------------------------------------------------------

**6. DynamoDB Streams for Reactive Workflows**

Use DynamoDB Streams + AWS Lambda to react to data changes without
slowing down hot paths. The book demonstrates this in the Big Time Deals
example:

-   Lambda listens to DynamoDB Stream for new Deal items

-   On new Deal: Query BrandWatch partition for all watchers → create
    Message for each watcher

-   On new Deal: Query CategoryWatch partition for all watchers → create
    Message for each watcher

-   On new Deal: Cache latest deals across multiple DynamoDB items to
    prevent hot partitions

**7. Handle Hot Partitions with Sharding**

When a partition will receive disproportionate read/write traffic, shard
the data across multiple partitions.

  ------------------------------------------------------------------------
  **Sharding         **How It Works**            **When to Use**
  Strategy**                                     
  ------------------ --------------------------- -------------------------
  Timestamp-based    Group items by truncated    \'Fetch most recent
  partitioning       timestamp (day/week/month). deals\' across the entire
                     Query multiple partitions   app. Groups \~100
                     in application code.        deals/day per partition.

  Random shard +     Write N copies of data to   High-read, low-write data
  read fan-out       DEALSCACHE#1 through        like front-page caches.
                     DEALSCACHE#N. Read from a   Spreads reads across N
                     random shard.               partitions.

  Sparse index for   Add a UserIndex attribute   \'Find all users\'
  \'find all\'       only to User items. Scan    patterns where you can\'t
                     this index instead of the   put them all in one
                     main table.                 partition safely.
  ------------------------------------------------------------------------

  -----------------------------------------------------------------------
  *From the book: \'We will very likely have a hot key issue where one
  partition in our database is read significantly more frequently than
  others. The good thing is that this access pattern is knowable in
  advance and thus easily cacheable.\'*

  -----------------------------------------------------------------------

**8. Filter Expression vs. Sort Key Design**

The book provides explicit guidance on when to use each approach:

  ------------------------------------------------------------------------
  **Approach**       **Use When**           **Avoid When**
  ------------------ ---------------------- ------------------------------
  Filter expression  Only 2 filter values   Poor maintenance ratio (many
                     (e.g., Open/Closed),   open, few closed), need to
                     small number of items  guarantee 25 results per page
                     per page (\<25), high  without over-reading
                     hit rate expected      

  Composite sort key Consistent filtering   Only 2 filter values with high
                     needed, query          hit rate and small pages
                     correctness is         (filter expression may be
                     critical, performance  simpler)
                     degradation noticed in 
                     production             
  ------------------------------------------------------------------------

  -----------------------------------------------------------------------
  *From Chapter 22 (GitHub): The book intentionally showed the filter
  expression approach first, then showed the migration to composite sort
  keys when the filter expression caused production problems. This
  teaches the cost of the wrong choice.*

  -----------------------------------------------------------------------

**9. Singleton Items for Global State and Caches**

Use a fixed, non-parameterized PK/SK for items that represent global
application state or page-level data.

  ------------------------------------------------------------------------------
  **Singleton Item**  **PK**             **SK**             **Contains**
  ------------------- ------------------ ------------------ --------------------
  Brands list         BRANDS             BRANDS             All brand names as a
                                                            string set

  Front Page          FRONTPAGE          FRONTPAGE          5-10 featured deals
                                                            as a list attribute

  Editor\'s Choice    EDITORSCHOICE      EDITORSCHOICE      Editor-curated deals
                                                            as a list attribute

  Deals Cache         DEALSCACHE#\<N\>   DEALSCACHE#\<N\>   Last 2 days of
  (sharded)                                                 deals, copied N
                                                            times for read
                                                            scaling
  ------------------------------------------------------------------------------

**10. Document Entity Charts in Your Repository**

After completing a data model, create entity charts and store them in
your repository documentation. From Chapter 19: \'You should include
them in the documentation for your repository to assist others in
knowing how the table is configured. You don\'t want to make them dig
through your data access layer.\'

-   One entity chart per index (base table + GSI1 + GSI2 + \...)

-   Include: entity name, PK pattern, SK pattern

-   Keep separate from ERD --- ERD shows business relationships, entity
    chart shows DynamoDB implementation

**Part VI --- Case Study Design Solutions**

**Chapter 18: Session Store**

Simple authentication session management. One entity, single table,
simple primary key.

**Table Structure**

  ------------------------------------------------------------------------
  **Attribute**      **Type**      **Notes**
  ------------------ ------------- ---------------------------------------
  SessionToken (PK)  String (UUID) Partition key --- also enforces
                                   uniqueness via condition expression

  Username           String        Links session to user

  CreatedAt          String        Human-readable creation time
                     (ISO8601)     

  ExpiresAt          String        Human-readable expiry
                     (ISO8601)     

  TTL                Number        DynamoDB TTL for auto-deletion after 7
                     (Epoch)       days
  ------------------------------------------------------------------------

**GSI: UserIndex**

  ------------------------------------------------------------------------
  **Key**            **Value**              **Projection**
  ------------------ ---------------------- ------------------------------
  Partition Key      Username               Groups all sessions for a user
  (GSI)                                     

  Projection         KEYS_ONLY              Only SessionToken is copied
                                            --- no application attributes
                                            needed
  ------------------------------------------------------------------------

**Access Patterns**

  -----------------------------------------------------------------------------------
  **Pattern**        **Index**   **Key           **Implementation**
                                 Parameters**    
  ------------------ ----------- --------------- ------------------------------------
  Create Session     Main        SessionToken    PutItem +
                                                 attribute_not_exists(SessionToken)
                                                 condition

  Get Session        Main        SessionToken    Query + FilterExpression: TTL \>
                                                 current_epoch

  Delete Session     None        None            DynamoDB TTL handles automatically
  (time-based)                                   --- no code needed

  Delete Sessions    UserIndex → Username →      Query GSI, then DeleteItem for each
  for User           Main        SessionToken    token found
  -----------------------------------------------------------------------------------

  -----------------------------------------------------------------------

  -----------------------------------------------------------------------

**Chapter 19: E-Commerce Application**

Customers, addresses, orders, and order items. Demonstrates primary key
overloading and composite sort key patterns.

**Entity Chart --- Base Table**

  ------------------------------------------------------------------------------------------------------
  **Entity**      **PK**                              **SK**                              **Notes**
  --------------- ----------------------------------- ----------------------------------- --------------
  Customer        CUSTOMER#\<Username\>               CUSTOMER#\<Username\>               Core entity
                                                                                          --- parent for
                                                                                          Orders

  CustomerEmail   CUSTOMEREMAIL#\<Email\>             CUSTOMEREMAIL#\<Email\>             Uniqueness
                                                                                          tracking item
                                                                                          only --- no
                                                                                          customer data
                                                                                          stored here

  Address         N/A                                 N/A                                 Denormalized
                                                                                          onto Customer
                                                                                          item as
                                                                                          Addresses map
                                                                                          attribute
                                                                                          (bounded to
                                                                                          \~20)

  Order           CUSTOMER#\<Username\>               #ORDER#\<KSUID\>                    \# prefix:
                                                                                          Order sorts
                                                                                          before
                                                                                          Customer,
                                                                                          enabling
                                                                                          descending
                                                                                          fetch

  OrderItem       ORDER#\<OrderId\>#ITEM#\<ItemId\>   ORDER#\<OrderId\>#ITEM#\<ItemId\>   Standalone in
                                                                                          base table
  ------------------------------------------------------------------------------------------------------

**Entity Chart --- GSI1**

  ---------------------------------------------------------------------------
  **Entity**      **GSI1PK**          **GSI1SK**          **Purpose**
  --------------- ------------------- ------------------- -------------------
  Order           ORDER#\<OrderId\>   ORDER#\<OrderId\>   Co-locate Order
                                                          with its OrderItems

  OrderItem       ORDER#\<OrderId\>   ITEM#\<ItemId\>     Enables: fetch
                                                          Order + all
                                                          OrderItems in one
                                                          Query on GSI1
  ---------------------------------------------------------------------------

**Access Patterns**

  --------------------------------------------------------------------------
  **Pattern**            **Index**   **Notes**
  ---------------------- ----------- ---------------------------------------
  Create Customer        Main        TransactWriteItems: PutItem(Customer) +
  (unique username +                 PutItem(CustomerEmail), each with
  email)                             attribute_not_exists condition

  View Customer + Most   Main        Query PK=CUSTOMER#\<username\>,
  Recent Orders                      ScanIndexForward=False, Limit=11 (1
                                     Customer + 10 Orders)

  View Order + Order     GSI1        Query GSI1PK=ORDER#\<orderId\> returns
  Items                              Order item + all OrderItems

  Create/Update/Delete   Main        UpdateItem on Customer item\'s
  Address                            Addresses map attribute
  --------------------------------------------------------------------------

**Why \# prefix on Order sort key?**

When fetching Customer + most recent Orders with ScanIndexForward=False,
DynamoDB reads from the end of the item collection backward. Without the
\# prefix, Order items (ORDER#\...) would sort AFTER the Customer item
(CUSTOMER#\...), meaning a reverse scan would return Customer first
without any Orders. The \# prefix (which sorts before alphabetic
characters) ensures Orders appear before the Customer in the sort order
--- so a reverse scan returns Customer + Orders in one pass.

  -----------------------------------------------------------------------

  -----------------------------------------------------------------------

**Chapter 20: Big Time Deals**

Complex deal discovery app with brands, categories, featured deals, user
interactions, and messaging. 23 access patterns.

**Entity Chart --- Base Table**

  --------------------------------------------------------------------------------------------------------
  **Entity**             **PK**                                   **SK**
  ---------------------- ---------------------------------------- ----------------------------------------
  Deal                   DEAL#\<DealId (KSUID)\>                  DEAL#\<DealId\>

  Brand                  BRAND#\<Brand\>                          BRAND#\<Brand\>

  Brands (singleton)     BRANDS                                   BRANDS

  BrandLike              BRANDLIKE#\<Brand\>#\<Username\>         BRANDLIKE#\<Brand\>#\<Username\>

  BrandWatch             BRANDWATCH#\<Brand\>                     USER#\<Username\>

  Category               CATEGORY#\<Category\>                    CATEGORY#\<Category\>

  CategoryLike           CATEGORYLIKE#\<Category\>#\<Username\>   CATEGORYLIKE#\<Category\>#\<Username\>

  CategoryWatch          CATEGORYWATCH#\<Category\>               USER#\<Username\>

  FrontPage (singleton)  FRONTPAGE                                FRONTPAGE

  EditorChoice           EDITORSCHOICE                            EDITORSCHOICE
  (singleton)                                                     

  User                   USER#\<Username\>                        USER#\<Username\>

  Message                MESSAGES#\<Username\>                    MESSAGE#\<MessageId (KSUID)\>
  --------------------------------------------------------------------------------------------------------

**GSI Structure**

  ------------------------------------------------------------------------------------------------------------------------
  **Index**   **Entity**       **GSI PK**                                     **GSI SK**              **Purpose**
  ----------- ---------------- ---------------------------------------------- ----------------------- --------------------
  GSI1        Deal             DEALS#\<TruncatedTimestamp\>                   DEAL#\<DealId\>         Latest deals overall
                                                                                                      (timestamp-sharded
                                                                                                      by day)

  GSI1        UnreadMessage    MESSAGES#\<Username\>                          MESSAGE#\<MessageId\>   Unread messages per
                                                                                                      user (sparse index)

  GSI2        Deal             BRAND#\<Brand\>#\<TruncatedTimestamp\>         DEAL#\<DealId\>         Latest deals by
                                                                                                      Brand

  GSI3        Deal             CATEGORY#\<Category\>#\<TruncatedTimestamp\>   DEAL#\<DealId\>         Latest deals by
                                                                                                      Category

  UserIndex   User             UserIndex attr = USER#\<Username\>             N/A                     Sparse index ---
                                                                                                      only User items.
                                                                                                      Used for \'find all
                                                                                                      users\' to blast
                                                                                                      messages.
  ------------------------------------------------------------------------------------------------------------------------

**Key Design Decisions**

-   Timestamp-sharded partitions: Deal items grouped by DEALS#\<date\>
    to avoid a single mega-partition. Query multiple day-partitions in
    application code to get 25 deals.

-   Read-sharding cache: DEALSCACHE#1 through DEALSCACHE#N --- identical
    copies of latest deals stored across N partitions. Read from random
    shard to spread load.

-   Featured deals via complex attribute: Category\'s featured deals
    stored directly on Category item as a list attribute. Set by
    internal CMS in one write.

-   Singleton items for front page and editor\'s choice: fixed FRONTPAGE
    and EDITORSCHOICE items contain all featured deals as list
    attributes.

-   Brand Likes/Watches via transactions: PutItem(BrandLike) with
    condition + UpdateItem(LikesCount++) on Brand --- atomic and
    idempotent.

-   Sparse index for unread messages: GSI1PK/GSI1SK only present on
    unread Message items. Removed on mark-as-read.

-   DynamoDB Streams for messaging: Lambda reacts to new Deal events,
    queries BrandWatch/CategoryWatch partitions, creates Message items
    for each watcher.

  -----------------------------------------------------------------------

  -----------------------------------------------------------------------

**Chapter 21: GitHub Backend Clone**

The most complex example. 10+ entity types, 24 access patterns, 3
secondary indexes. Demonstrates multiple one-to-many, many-to-many,
shared namespaces, and reference counts.

**Entity Chart --- Base Table**

  -----------------------------------------------------------------------------------------------------------------------------------------
  **Entity**                **PK**                                                          **SK**
  ------------------------- --------------------------------------------------------------- -----------------------------------------------
  Repo                      REPO#\<Owner\>#\<RepoName\>                                     REPO#\<Owner\>#\<RepoName\>

  Issue                     REPO#\<Owner\>#\<RepoName\>                                     ISSUE#\<ZeroPaddedNumber\>

  Pull Request              PR#\<Owner\>#\<RepoName\>#\<ZeroPaddedPRNum\>                   PR#\<Owner\>#\<RepoName\>#\<ZeroPaddedPRNum\>

  IssueComment              ISSUECOMMENT#\<Owner\>#\<RepoName\>#\<IssueNum\>                ISSUECOMMENT#\<CommentId\>

  PRComment                 PRCOMMENT#\<Owner\>#\<RepoName\>#\<PRNum\>                      PRCOMMENT#\<CommentId\>

  Reaction                  \<TargetType\>REACTION#\<Owner\>#\<Repo\>#\<Target\>#\<User\>   \<same as PK\>

  Star                      REPO#\<Owner\>#\<RepoName\>                                     STAR#\<Username\>

  User                      ACCOUNT#\<Username\>                                            ACCOUNT#\<Username\>

  Organization              ACCOUNT#\<OrgName\>                                             ACCOUNT#\<OrgName\>

  Membership                ACCOUNT#\<OrgName\>                                             MEMBERSHIP#\<Username\>
  -----------------------------------------------------------------------------------------------------------------------------------------

**GSI Structure (Chapter 21)**

  ----------------------------------------------------------------------------------------------------------------
  **Index**   **Entity**       **GSI PK**                            **GSI SK**                    **Purpose**
  ----------- ---------------- ------------------------------------- ----------------------------- ---------------
  GSI1        Repo             REPO#\<Owner\>#\<RepoName\>           REPO#\<Owner\>#\<RepoName\>   Co-locate
                                                                                                   Repo + Pull
                                                                                                   Requests

  GSI1        Pull Request     REPO#\<Owner\>#\<RepoName\>           PR#\<ZeroPaddedPRNum\>        Fetch Repo +
                                                                                                   most recent PRs

  GSI2        Repo (original)  REPO#\<Owner\>#\<RepoName\>           #REPO#\<RepoName\>            Co-locate
                                                                                                   Repo + its
                                                                                                   Forks

  GSI2        Fork (is a Repo) REPO#\<OriginalOwner\>#\<RepoName\>   FORK#\<ForkOwner\>            Forks sorted by
                                                                                                   owner name
                                                                                                   ascending

  GSI3        Repo             ACCOUNT#\<AccountName\>               #\<UpdatedAt\>                Repos sorted by
                                                                                                   last updated
                                                                                                   per account

  GSI3        User             ACCOUNT#\<Username\>                  ACCOUNT#\<Username\>          Enables
                                                                                                   account-level
                                                                                                   queries

  GSI3        Organization     ACCOUNT#\<OrgName\>                   ACCOUNT#\<OrgName\>           Same as User in
                                                                                                   GSI3
  ----------------------------------------------------------------------------------------------------------------

**Key Design Decisions**

-   Two one-to-many in one item collection: Repo item placed between
    Issues (sorted before REPO#) and Stars (sorted after REPO#). One
    reverse scan gets Repo + Issues. One forward scan from REPO#\...
    gets Repo + Stars.

-   Shared Issue/PR counter: IssuesAndPullRequestCount attribute on Repo
    item. Atomically increment with UpdateItem ReturnValues=UPDATED_NEW,
    then use returned value as the new Issue/PR number.

-   Zero-padded issue numbers: Sort key uses ISSUE#00000015, not
    ISSUE#15, to ensure correct lexicographic ordering of numeric
    strings.

-   Shared ACCOUNT# namespace: Users and Organizations share PK prefix
    ACCOUNT# because they compete for unique names in GitHub. Type
    attribute distinguishes them.

-   Payment Plan as complex attribute: one-to-one relationship stored as
    a map on User/Org item directly.

-   Organizations on User as complex attribute: bounded many-to-many ---
    a user won\'t belong to thousands of orgs, so stored as map on User
    item. Membership items handle the unbounded \'users in org\'
    direction.

-   Reaction counts as map attribute: ReactionCounts: { \'Heart\': 5,
    \'ThumbsUp\': 12, \... } stored on Issue/PR/Comment item. Reaction
    tracking item uses a string set attribute.

  -----------------------------------------------------------------------

  -----------------------------------------------------------------------

**Chapter 22: GitHub Migration (Applying Ch15 Patterns)**

Four concrete changes applied to the GitHub model demonstrate every
migration strategy.

  --------------------------------------------------------------------------------
  **Migration**       **Type**        **Additive?**   **Strategy Used**
  ------------------- --------------- --------------- ----------------------------
  Code of Conduct on  New attribute   Yes             Lazy attribute:
  Repo                (one-to-one)                    CodeOfConduct map attribute
                                                      added to Repo item on demand

  GitHub Gists        New entity into Yes             Reused User\'s empty item
                      existing                        collection: SK =
                      collection                      #GIST#\<KSUID\>

  GitHub Apps (owner  New entity      No              Batch Scan+UpdateItem on
  relationship)       needing new GSI                 Users/Orgs to add
                      collection                      GSI1PK/GSI1SK, then new item
                                                      collection in GSI1

  GitHub Apps (repo   Many-to-many    No              Adjacency list:
  installations)                                      AppInstallation PK=APP#\...,
                                                      SK=REPO#\... lives in App
                                                      collection; GSI1PK=REPO#\...
                                                      projects it into Repo
                                                      collection

  Open/Closed Issue   Refactor        No              New composite SK:
  filtering           existing                        ISSUE#OPEN#\<NumDiff\> and
                      pattern                         #ISSUE#CLOSED#\<Num\>. Two
                                                      new GSIs (GSI4, GSI5). Batch
                                                      Scan+UpdateItem on all
                                                      Issues and PRs.
  --------------------------------------------------------------------------------

**Final Entity Chart After Migration (Chapter 22)**

  --------------------------------------------------------------------------------------------------------------------------------------
  **Entity**             **PK**                                                          **SK**
  ---------------------- --------------------------------------------------------------- -----------------------------------------------
  Repo                   REPO#\<Owner\>#\<RepoName\>                                     REPO#\<Owner\>#\<RepoName\>

  CodeOfConduct          N/A (attribute on Repo)                                         N/A

  Issue                  REPO#\<Owner\>#\<RepoName\>                                     ISSUE#\<ZeroPaddedNumber\>

  Pull Request           PR#\<Owner\>#\<RepoName\>#\<ZeroPaddedPRNum\>                   PR#\<Owner\>#\<RepoName\>#\<ZeroPaddedPRNum\>

  IssueComment           ISSUECOMMENT#\<Owner\>#\<Repo\>#\<IssueNum\>                    ISSUECOMMENT#\<CommentId\>

  PRComment              PRCOMMENT#\<Owner\>#\<Repo\>#\<PRNum\>                          PRCOMMENT#\<CommentId\>

  Reaction               \<TargetType\>REACTION#\<Owner\>#\<Repo\>#\<Target\>#\<User\>   \<same\>

  User                   ACCOUNT#\<Username\>                                            ACCOUNT#\<Username\>

  Gist                   ACCOUNT#\<Username\>                                            #GIST#\<GistId\>

  Organization           ACCOUNT#\<OrgName\>                                             ACCOUNT#\<OrgName\>

  Membership             ACCOUNT#\<OrgName\>                                             MEMBERSHIP#\<Username\>

  GitHubApp              APP#\<AccountName\>#\<AppName\>                                 APP#\<AccountName\>#\<AppName\>

  AppInstallation        APP#\<AccountName\>#\<AppName\>                                 REPO#\<RepoOwner\>#\<RepoName\>
  --------------------------------------------------------------------------------------------------------------------------------------

**GSI Structure After Migration**

  -------------------------------------------------------------------------------------------------------
  **Index**   **Entity**         **GSI PK**                            **GSI SK**
  ----------- ------------------ ------------------------------------- ----------------------------------
  GSI1        Repo               REPO#\<Owner\>#\<RepoName\>           REPO#\<Owner\>#\<RepoName\>

  GSI1        Pull Request       REPO#\<Owner\>#\<RepoName\>           PR#\<ZeroPaddedPRNum\>

  GSI1        User / Org         ACCOUNT#\<AccountName\>               ACCOUNT#\<AccountName\>

  GSI1        GitHubApp          ACCOUNT#\<AccountName\>               APP#\<AppName\>

  GSI1        AppInstallation    REPO#\<RepoOwner\>#\<RepoName\>       REPOAPP#\<AppOwner\>#\<AppName\>

  GSI2        Repo (original)    REPO#\<Owner\>#\<RepoName\>           #REPO#\<RepoName\>

  GSI2        Fork               REPO#\<OriginalOwner\>#\<RepoName\>   FORK#\<Owner\>

  GSI3        Repo               ACCOUNT#\<AccountName\>               #\<UpdatedAt\>

  GSI3        User / Org         ACCOUNT#\<AccountName\>               ACCOUNT#\<AccountName\>

  GSI4        Repo               REPO#\<Owner\>#\<RepoName\>           #REPO#\<Owner\>#\<RepoName\>

  GSI4        Open Issue         REPO#\<Owner\>#\<RepoName\>           ISSUE#OPEN#\<NumDifference\>

  GSI4        Closed Issue       REPO#\<Owner\>#\<RepoName\>           #ISSUE#CLOSED#\<IssueNumber\>

  GSI5        Repo               REPO#\<Owner\>#\<RepoName\>           #REPO#\<Owner\>#\<RepoName\>

  GSI5        Open PR            REPO#\<Owner\>#\<RepoName\>           PR#OPEN#\<NumDifference\>

  GSI5        Closed PR          REPO#\<Owner\>#\<RepoName\>           #PR#CLOSED#\<PRNumber\>
  -------------------------------------------------------------------------------------------------------

**Part VII --- Quick Reference: All Patterns**

**Complete Pattern Reference (Chapters 15--22)**

  ----------------------------------------------------------------------------------------------
  **Pattern**         **Chapter**   **What It Solves**    **Key Mechanism**
  ------------------- ------------- --------------------- --------------------------------------
  Lazy attribute      15, 22        Adding optional       Application code handles missing
  loading                           attributes to         attributes with defaults
                                    existing entities     

  New entity, new     15            New entity with no    Write new items immediately --- no ETL
  collection                        relational pattern    

  New entity,         15, 22        New entity co-located Match parent PK, new SK prefix. No
  existing collection               with parent           ETL.

  New entity, new GSI 15, 22        New entity +          Batch Scan+UpdateItem to add GSI
  collection                        relational pattern,   attributes to existing parents
                                    no space in base      
                                    table                 

  Parallel scan ETL   15, 22        Speed up batch        TotalSegments + Segment parameters
                                    migrations            

  Multi-attribute     16, 19        Unique on 2+          TransactWriteItems with two condition
  uniqueness                        attributes            expressions

  Sequential IDs      16, 21        User-facing numeric   Atomic counter with
                                    identifiers           ReturnValues=UPDATED_NEW

  Cursor pagination   16, 19        Paginated API         KSUID/last-seen sort key value
                                    responses             embedded in URL

  Singleton items     16, 20        Global state,         Fixed PK/SK (non-parameterized)
                                    page-level caches     

  Reference counts    16, 20, 21    Counts without        TransactWriteItems: child PutItem +
                                    scanning              parent UpdateItem

  Simple primary key  18            Single entity,        Descriptive partition key name
                                    key-value only        

  TTL auto-expiry     18            Time-based item       TTL attribute (epoch) +
                                    deletion              FilterExpression on reads

  KEYS_ONLY GSI       18            Lookup IDs, query     GSI projection = KEYS_ONLY
                                    main table separately 

  Pre-join via item   19, 20, 21    Fetch parent +        Match partition key, use sort key to
  collection                        children in one Query distinguish entities

  \# prefix trick     19, 21        Control parent        \# sorts before letters --- parent
                                    position in sort      appears at end ascending / start
                                    order                 descending

  Composite sort key  13, 22        Filter on multiple    SK =
                                    dimensions via key    PREFIX#\<FilterValue\>#\<SortValue\>

  Zero-padded         14, 21, 22    Correct lexicographic Pad to fixed width (8 digits) in sort
  integers                          ordering of numeric   key
                                    strings               

  Numeric difference  22            Reverse ordering of   Use (maxValue - actualValue) in sort
  trick                             integers in a forward key
                                    scan                  

  Denormalization     19, 20, 21    Bounded one-to-many   Store as map/list attribute on parent
  (complex attribute)               or one-to-one         item

  Adjacency list      22            Many-to-many with     Link item lives in one collection in
                                    both sides needing    base table, projected into other via
                                    fetch                 GSI

  Sparse index        20            Find all items of a   Add GSI attribute only to target type
  (filter by type)                  single entity type    items; scan or query the sparse index

  Sparse index        20            Subset of entity type Add GSI attribute conditionally;
  (filter within                    (e.g., unread         remove it when condition no longer
  type)                             messages)             applies

  Timestamp-sharded   20            Prevent hot           GSI PK = PREFIX#\<TruncatedDate\>;
  partitions                        partitions for        query multiple dates in application
                                    time-series data      

  Read-sharding cache 20            High-read hot         Write N identical copies; read from
                                    partitions            random shard

  Shared namespace    21            Two entity types      Same PK prefix (ACCOUNT#); Type
                                    competing for unique  attribute distinguishes them
                                    names                 

  DynamoDB Streams +  20            Reactive workflows    Lambda triggers on table events to fan
  Lambda                            without slowing hot   out messages or update caches
                                    paths                 
  ----------------------------------------------------------------------------------------------

*--- End of DynamoDB Design Solutions (Chapters 15--22) ---*
