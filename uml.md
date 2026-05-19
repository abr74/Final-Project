@startuml

title NETFEELINGS Web Application UML Aspect

package "Frontend React Application" {
  class App {
    +render()
  }

  class Landing {
    +handleUpload(file)
    +render()
  }

  class UploadTakeoutForm {
    +selectedFile: File
    +validateFile()
    +requestUploadUrl()
    +uploadToS3()
  }

  class Dashboard {
    -tasteProfile: TasteProfile
    -history: WatchHistory
    -recommendations: Recommendation[]
    +loadResults()
    +render()
  }

  class TopNavigation {
    +brand: String
    +links: String[]
    +render()
  }

  class TasteProfilePanel {
    +displayLikedAspects()
    +displayAspectPreferences()
  }

  class WatchHistoryPanel {
    +displayHistory()
  }

  class RecommendationPanel {
    +displayRecommendations()
  }

  class ProgressBar {
    +label: String
    +value: Number
    +render()
  }
}

package "User and Data Models" {
  class User {
    +userId: String
    +sessionId: String
  }

  class TakeoutUpload {
    +uploadId: String
    +fileName: String
    +fileType: String
    +uploadTime: Date
    +status: String
    +s3RawKey: String
    +s3ParsedKey: String
  }

  class ParsedTakeoutData {
    +records: Object[]
    +counts: Object
    +generatedAt: Date
  }

  class TasteProfile {
    +likedAspects: String[]
    +aspectPreferences: AspectPreference[]
  }

  class AspectPreference {
    +label: String
    +value: Number
  }

  class WatchHistory {
    +movies: Movie[]
    +youtubeVideos: Object[]
  }

  class Movie {
    +movieId: String
    +title: String
    +imageUrl: String
    +genre: String
  }

  class Recommendation {
    +movie: Movie
    +score: Number
    +reason: String
  }
}

package "AWS Backend" {
  class APIGateway {
    +createPresignedUploadUrl()
    +getProcessingStatus()
    +getRecommendations()
  }

  class S3RawTakeoutBucket {
    +storeRawTakeoutZip()
  }

  class ParserLambda {
    +downloadTakeoutFromS3()
    +processTakeoutFile()
    +extractWatchHistory()
    +writeParsedOutput()
  }

  class S3ParsedOutputBucket {
    +storeCentralOutputJson()
    +storeJsonlFiles()
  }

  class RecommendationLambda {
    +loadParsedTakeoutData()
    +prepareUserData()
    +requestAIRecommendations()
    +returnRecommendations()
  }

  class Database {
    +users
    +uploads
    +watchHistory
    +tasteProfiles
    +recommendations
    +processingStatus
  }
}

package "AI Recommendation System" {
  class AIModel {
    +analyzeWatchHistory()
    +generateTasteProfile()
    +generateRecommendations()
  }

  class BERTModel {
    +analyzeMovieText()
  }

  class NCFModel {
    +predictUserPreference()
  }

  class ContentAIModel {
    +compareMovieFeatures()
  }
}

App --> Landing : displays upload page
App --> Dashboard : displays results

Landing --> UploadTakeoutForm : contains
UploadTakeoutForm --> APIGateway : requests upload URL
APIGateway --> S3RawTakeoutBucket : creates presigned URL
UploadTakeoutForm --> S3RawTakeoutBucket : uploads Takeout ZIP

S3RawTakeoutBucket --> ParserLambda : triggers parse event
ParserLambda --> S3RawTakeoutBucket : downloads raw ZIP
ParserLambda --> ParsedTakeoutData : creates
ParserLambda --> S3ParsedOutputBucket : stores parsed JSON output
ParserLambda --> Database : updates upload status

Dashboard --> APIGateway : requests results
APIGateway --> RecommendationLambda : routes request
RecommendationLambda --> S3ParsedOutputBucket : loads parsed data
RecommendationLambda --> Database : loads user/upload info
RecommendationLambda --> AIModel : sends parsed watch data

AIModel --> TasteProfile : creates
AIModel --> Recommendation : creates
AIModel --> BERTModel : uses
AIModel --> NCFModel : uses
AIModel --> ContentAIModel : uses

RecommendationLambda --> Database : stores recommendations
RecommendationLambda --> APIGateway : returns profile and recommendations
APIGateway --> Dashboard : sends results

Dashboard --> TopNavigation : contains
Dashboard --> TasteProfilePanel : contains
Dashboard --> WatchHistoryPanel : contains
Dashboard --> RecommendationPanel : contains

TasteProfilePanel --> TasteProfile : displays
TasteProfile --> AspectPreference : contains
TasteProfilePanel --> ProgressBar : uses

WatchHistoryPanel --> WatchHistory : displays
WatchHistory --> Movie : contains

RecommendationPanel --> Recommendation : displays
Recommendation --> Movie : recommends

User "1" --> "many" TakeoutUpload
User "1" --> "1" WatchHistory
User "1" --> "1" TasteProfile
User "1" --> "many" Recommendation
TakeoutUpload "1" --> "1" ParsedTakeoutData
WatchHistory "1" --> "many" Movie
TasteProfile "1" --> "many" AspectPreference

@enduml