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

  class Dashboard {
    -prefs: String[]
    -aspectPrefs: AspectPreference[]
    -history: Movie[]
    +render()
  }

  class UploadTakeoutForm {
    +selectedFile: File
    +validateFile()
    +uploadTakeout()
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
    +fileName: String
    +fileType: String
    +uploadTime: Date
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
    +receiveUploadRequest()
    +routeToLambda()
    +routeToAIModel()
  }

  class UploadLambda {
    +processTakeoutFile()
    +extractWatchHistory()
    +storeParsedData()
  }

  class RecommendationLambda {
    +prepareUserData()
    +requestAIRecommendations()
    +returnRecommendations()
  }

  class Database {
    +users
    +uploads
    +movies
    +watchHistory
    +tasteProfiles
    +recommendations
  }

  class S3Bucket {
    +storeRawTakeoutFile()
    +retrieveTakeoutFile()
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
UploadTakeoutForm --> TakeoutUpload : creates
UploadTakeoutForm --> APIGateway : uploads file

APIGateway --> UploadLambda : sends upload request
UploadLambda --> S3Bucket : stores raw Takeout file
UploadLambda --> WatchHistory : extracts data
UploadLambda --> Database : stores parsed data

Dashboard --> APIGateway : requests results
APIGateway --> RecommendationLambda : sends recommendation request

RecommendationLambda --> Database : gets watch history
RecommendationLambda --> AIModel : sends user data
AIModel --> TasteProfile : creates
AIModel --> Recommendation : creates

AIModel --> BERTModel : uses
AIModel --> NCFModel : uses
AIModel --> ContentAIModel : uses

RecommendationLambda --> Database : stores recommendations
RecommendationLambda --> APIGateway : returns results
APIGateway --> Dashboard : sends profile and recommendations

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
WatchHistory "1" --> "many" Movie
TasteProfile "1" --> "many" AspectPreference

@enduml